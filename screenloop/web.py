import hashlib
import ipaddress
import json
import secrets
import shutil
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import APP_NAME
from . import config
from .i18n import DEFAULT_LOCALE, normalize_locale, translate
from .profiles import PROFILES, detect_profile, profile_or_default
from .security import create_csrf_token, verify_csrf_token, verify_stream_token
from .store import Store
from .transcode import VIDEO_EXTENSIONS, media_digest, probe_duration_seconds
from .worker import Worker


config.ensure_dirs()
store = Store()
worker = Worker(store)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["default_password"] = store.user_count() == 0 and config.BOOTSTRAP_PASSWORD in {"", "admin", "change-me", "1234"}
API_TAGS = [
    {"name": "health", "description": "Public healthcheck without sensitive data."},
    {"name": "auth", "description": "Cookie session authentication and CSRF token bootstrap."},
    {"name": "status", "description": "Live dashboard state for polling UIs."},
    {"name": "media", "description": "Uploaded media library and upload/delete operations."},
    {"name": "playlists", "description": "Playlist CRUD, item management, and ordering."},
    {"name": "tvs", "description": "TV configuration, discovery, import/export, and playback commands."},
    {"name": "transcode", "description": "Transcode job state, rebuilds, and cache cleanup."},
    {"name": "events", "description": "Audit and service event log."},
    {"name": "users", "description": "Local users, roles, and password administration."},
]

app = FastAPI(
    title=APP_NAME,
    version="0.3.0-dev",
    summary="Local TV playlist daemon and DLNA control API.",
    description=(
        "Screenloop controls local TVs and signage screens over DLNA/UPnP. "
        "The `/api/v1` API is intended for the future Vue web UI and trusted LAN integrations. "
        "Authentication uses an HttpOnly `screenloop_session` cookie. Unsafe methods require "
        "`X-CSRF-Token`, retrieved from `/api/v1/session` or `/api/v1/auth/login`."
    ),
    openapi_tags=API_TAGS,
)
_auth_failures: dict[str, deque[float]] = defaultdict(deque)
_action_failures: dict[str, deque[float]] = defaultdict(deque)
ROLE_LEVELS = {"viewer": 1, "operator": 2, "admin": 3}
RoleName = Literal["admin", "operator", "viewer"]
TvCommandName = Literal["play_next", "stop", "restart_playlist", "rediscover"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class TvCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    ip: str = Field(min_length=1, max_length=128)
    profile: str = "generic_dlna"


class TvUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    ip: str = Field(min_length=1, max_length=128)
    profile: str = "generic_dlna"
    playlist_id: int | None = None
    autoplay: bool = True
    control_url: str | None = None


class TvCommandRequest(BaseModel):
    command: TvCommandName


class PlaylistCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class PlaylistItemRequest(BaseModel):
    media_id: int


class PlaylistMoveRequest(BaseModel):
    direction: Literal["up", "down"]


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)
    role: RoleName = "viewer"


class UserUpdateRequest(BaseModel):
    role: RoleName
    disabled: bool = False


class PasswordChangeRequest(BaseModel):
    password: str = Field(min_length=1, max_length=512)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
    )
    return response


def page_context(request: Request, **extra: Any) -> dict[str, Any]:
    locale = normalize_locale(request.query_params.get("lang") or request.cookies.get("screenloop_lang"))
    session_token = request.cookies.get("screenloop_session", "")
    csrf = create_csrf_token(session_token)
    return {
        "request": request,
        "locale": locale,
        "t": lambda text: translate(locale, text),
        "current_user": getattr(request.state, "user", None),
        "csrf_token": csrf,
        "csrf_field": f'<input type="hidden" name="csrf_token" value="{csrf}">',
        **extra,
    }


def client_ip(request: Request) -> str:
    direct = request.client.host if request.client else "unknown"
    if trusted_proxy(direct):
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return direct


def trusted_proxy(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in ipaddress.ip_network(cidr, strict=False) for cidr in config.TRUSTED_PROXY_CIDRS)
    except ValueError:
        return False


def rate_limited(bucket: dict[str, deque[float]], key: str, limit: int, window: int) -> bool:
    now = time.time()
    failures = bucket[key]
    while failures and now - failures[0] > window:
        failures.popleft()
    return len(failures) >= limit


def record_failure(bucket: dict[str, deque[float]], key: str) -> None:
    bucket[key].append(time.time())


def csrf_guard(request: Request, csrf_token: str = Form("")) -> None:
    session_token = request.cookies.get("screenloop_session", "")
    if not verify_csrf_token(csrf_token, session_token):
        raise HTTPException(403, "Invalid CSRF token")


def require_auth(request: Request) -> dict[str, Any]:
    token = request.cookies.get("screenloop_session")
    user = store.get_session_user(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    request.state.user = user
    return user


def require_role(role: str):
    def dependency(request: Request, user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
        if ROLE_LEVELS.get(user["role"], 0) < ROLE_LEVELS[role]:
            store.add_event(None, "security_denied", f"Denied {request.method} {request.url.path}", user["username"])
            raise HTTPException(403, "Insufficient permissions")
        return user

    return dependency


def require_api_auth(request: Request) -> dict[str, Any]:
    token = request.cookies.get("screenloop_session")
    user = store.get_session_user(token)
    if not user:
        raise HTTPException(401, "Authentication required")
    request.state.user = user
    return user


def require_api_role(role: str):
    def dependency(request: Request, user: dict[str, Any] = Depends(require_api_auth)) -> dict[str, Any]:
        if ROLE_LEVELS.get(user["role"], 0) < ROLE_LEVELS[role]:
            store.add_event(None, "security_denied", f"Denied {request.method} {request.url.path}", user["username"])
            raise HTTPException(403, "Insufficient permissions")
        return user

    return dependency


def api_csrf_guard(request: Request) -> None:
    session_token = request.cookies.get("screenloop_session", "")
    csrf_token = request.headers.get("x-csrf-token", "")
    if not verify_csrf_token(csrf_token, session_token):
        raise HTTPException(403, "Invalid CSRF token")


def ensure_allowed_tv_ip(ip: str) -> None:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise HTTPException(400, "Invalid TV IP address") from exc
    if not config.ALLOWED_TV_CIDRS:
        return
    allowed = any(addr in ipaddress.ip_network(cidr, strict=False) for cidr in config.ALLOWED_TV_CIDRS)
    if not allowed:
        raise HTTPException(403, "TV IP is outside allowed networks")


def ensure_command_rate(request: Request, tv_id: int) -> None:
    key = f"command:{client_ip(request)}:{tv_id}"
    if rate_limited(_action_failures, key, 30, 60):
        raise HTTPException(429, "Too many TV commands")
    record_failure(_action_failures, key)


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "disabled": bool(user.get("disabled", 0)),
    }


def require_password_strength(password: str) -> None:
    if len(password) < 12 and not config.ALLOW_INSECURE_AUTH:
        raise HTTPException(400, "Password must contain at least 12 characters")


def tv_or_404(tv_id: int) -> dict[str, Any]:
    tv = store.get_tv(tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    return tv


def playlist_or_404(playlist_id: int) -> dict[str, Any]:
    playlist = store.get_playlist(playlist_id)
    if not playlist:
        raise HTTPException(404, "Playlist not found")
    return playlist


def save_upload(file: UploadFile, user: dict[str, Any]) -> int:
    original_name = Path(file.filename or "upload.bin").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(400, f"Unsupported video extension: {suffix}")

    digest = hashlib.sha1(f"{original_name}:{secrets.token_hex(8)}".encode()).hexdigest()[:16]
    target = config.MEDIA_DIR / f"{Path(original_name).stem}.{digest}{suffix}"
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    if target.stat().st_size > config.MAX_UPLOAD_BYTES:
        unlink_quiet(target)
        raise HTTPException(413, "Uploaded file is too large")
    duration = probe_duration_seconds(target)
    if duration is None:
        unlink_quiet(target)
        store.add_event(None, "upload_rejected", f"Rejected unreadable video {original_name}", user["username"])
        raise HTTPException(400, "Uploaded file is not a readable video")

    media_id = store.add_media(
        Path(original_name).stem,
        target,
        original_name,
        target.stat().st_size,
        media_digest(target),
        duration,
    )
    for profile in PROFILES:
        store.ensure_transcode_job(media_id, profile)
    store.add_event(None, "media_uploaded", f"Uploaded {original_name}", user["username"])
    return media_id


@app.on_event("startup")
def startup() -> None:
    config.validate_security_config()
    if store.user_count() == 0:
        config.validate_bootstrap_password()
    created = store.ensure_bootstrap_admin(config.BOOTSTRAP_USER, config.BOOTSTRAP_PASSWORD)
    if created:
        store.add_event(None, "security_bootstrap", f"Created bootstrap admin {config.BOOTSTRAP_USER}")
    store.cleanup_sessions()
    worker.start()


@app.on_event("shutdown")
def shutdown() -> None:
    worker.stop()


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", page_context(request))


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = client_ip(request)
    if rate_limited(_auth_failures, ip, 10, 300):
        store.add_event(None, "login_rate_limited", "Login rate limited", ip)
        raise HTTPException(429, "Too many login attempts")
    user = store.authenticate_user(username, password)
    if not user:
        record_failure(_auth_failures, ip)
        store.add_event(None, "login_failed", f"Login failed for {username}", ip)
        raise HTTPException(401, "Invalid credentials")
    token = store.create_session(user["id"], ip, request.headers.get("user-agent", ""))
    store.add_event(None, "login_success", f"Login success for {user['username']}", ip)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "screenloop_session",
        token,
        max_age=config.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
    )
    return response


@app.post("/logout")
def logout(request: Request, user: dict[str, Any] = Depends(require_auth), __: None = Depends(csrf_guard)):
    token = request.cookies.get("screenloop_session")
    store.delete_session(token)
    store.add_event(None, "logout", f"Logout {user.get('username')}")
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("screenloop_session")
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _: dict[str, Any] = Depends(require_auth)):
    return templates.TemplateResponse(
        "dashboard.html",
        page_context(request, tvs=store.list_tvs(), media=store.list_media(), playlists=store.list_playlists()),
    )


@app.get("/media", response_class=HTMLResponse)
def media_page(request: Request, _: dict[str, Any] = Depends(require_auth)):
    return templates.TemplateResponse("media.html", page_context(request, media=store.list_media()))


@app.get("/language/{locale}")
def set_language(locale: str, request: Request, _: dict[str, Any] = Depends(require_auth)):
    response = RedirectResponse(request.headers.get("referer") or "/", status_code=303)
    response.set_cookie("screenloop_lang", normalize_locale(locale), httponly=True, samesite="lax")
    return response


@app.post("/media/upload")
def upload_media(
    request: Request,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(require_role("operator")),
    __: None = Depends(csrf_guard),
):
    upload_key = f"upload:{client_ip(request)}"
    if rate_limited(_action_failures, upload_key, 20, 3600):
        raise HTTPException(429, "Too many uploads")
    record_failure(_action_failures, upload_key)
    save_upload(file, user)
    return RedirectResponse("/media", status_code=303)


@app.post("/media/{media_id}/delete")
def delete_media(media_id: int, user: dict[str, Any] = Depends(require_role("admin")), __: None = Depends(csrf_guard)):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    paths = [media["original_path"], *store.media_output_paths(media_id)]
    store.delete_media(media_id)
    for item in paths:
        unlink_quiet(Path(item))
    store.add_event(None, "media_deleted", f"Deleted media {media_id}", user["username"])
    return RedirectResponse("/media", status_code=303)


@app.get("/playlists", response_class=HTMLResponse)
def playlists_page(request: Request, _: dict[str, Any] = Depends(require_auth)):
    playlists = store.list_playlists()
    selected_id = int(request.query_params.get("id", playlists[0]["id"] if playlists else 0))
    selected = store.playlist_items(selected_id) if selected_id else []
    return templates.TemplateResponse(
        "playlists.html",
        page_context(request, playlists=playlists, selected_id=selected_id, items=selected, media=store.list_media()),
    )


@app.post("/playlists")
def create_playlist(name: str = Form(...), user: dict[str, Any] = Depends(require_role("operator")), __: None = Depends(csrf_guard)):
    store.create_playlist(name.strip())
    store.add_event(None, "playlist_created", f"Created playlist {name.strip()}", user["username"])
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{playlist_id}/delete")
def delete_playlist(playlist_id: int, user: dict[str, Any] = Depends(require_role("admin")), __: None = Depends(csrf_guard)):
    playlist = store.get_playlist(playlist_id)
    if not playlist:
        raise HTTPException(404, "Playlist not found")
    store.delete_playlist(playlist_id)
    store.add_event(None, "playlist_deleted", f"Deleted playlist {playlist['name']}", user["username"])
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{playlist_id}/items")
def add_playlist_item(
    playlist_id: int,
    media_id: int = Form(...),
    user: dict[str, Any] = Depends(require_role("operator")),
    __: None = Depends(csrf_guard),
):
    store.add_playlist_item(playlist_id, media_id)
    store.add_event(None, "playlist_item_added", f"Added media {media_id} to playlist {playlist_id}", user["username"])
    return RedirectResponse(f"/playlists?id={playlist_id}", status_code=303)


@app.post("/playlist-items/{item_id}/delete")
def delete_playlist_item(
    item_id: int,
    playlist_id: int = Form(...),
    user: dict[str, Any] = Depends(require_role("operator")),
    __: None = Depends(csrf_guard),
):
    store.remove_playlist_item(item_id)
    store.add_event(None, "playlist_item_removed", f"Removed playlist item {item_id}", user["username"])
    return RedirectResponse(f"/playlists?id={playlist_id}", status_code=303)


@app.post("/playlist-items/{item_id}/move")
def move_playlist_item(
    item_id: int,
    playlist_id: int = Form(...),
    direction: str = Form(...),
    user: dict[str, Any] = Depends(require_role("operator")),
    __: None = Depends(csrf_guard),
):
    store.move_playlist_item(item_id, direction)
    store.add_event(None, "playlist_item_moved", f"Moved playlist item {item_id} {direction}", user["username"])
    return RedirectResponse(f"/playlists?id={playlist_id}", status_code=303)


@app.get("/tvs", response_class=HTMLResponse)
def tvs_page(request: Request, _: dict[str, Any] = Depends(require_auth)):
    return templates.TemplateResponse(
        "tvs.html",
        page_context(request, tvs=store.list_tvs(), playlists=store.list_playlists(), profiles=PROFILES),
    )


@app.get("/tvs/export")
def export_tvs(_: dict[str, Any] = Depends(require_role("admin"))):
    payload = {
        "version": 1,
        "app": APP_NAME,
        "exported_at": int(time.time()),
        "tvs": store.export_tvs(),
    }
    return JSONResponse(
        payload,
        headers={"Content-Disposition": "attachment; filename=screenloop-tvs.json"},
    )


@app.post("/tvs/import")
def import_tvs(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(require_role("admin")),
    __: None = Depends(csrf_guard),
):
    try:
        payload = json.loads(file.file.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400, f"Invalid JSON import: {exc}") from exc
    tvs = payload.get("tvs") if isinstance(payload, dict) else payload
    if not isinstance(tvs, list):
        raise HTTPException(400, "Import must contain a tvs list")
    created, updated = store.import_tvs(tvs)
    store.add_event(None, "tv_import", f"Imported TV configs: {created} created, {updated} updated", user["username"])
    return RedirectResponse("/tvs", status_code=303)


@app.post("/tvs")
def add_tv(
    name: str = Form(...),
    ip: str = Form(...),
    user: dict[str, Any] = Depends(require_role("admin")),
    __: None = Depends(csrf_guard),
):
    ensure_allowed_tv_ip(ip.strip())
    store.add_tv(name.strip() or ip.strip(), ip.strip(), "generic_dlna")
    store.add_event(None, "tv_added", f"Added TV {ip.strip()}", user["username"])
    return RedirectResponse("/tvs", status_code=303)


@app.get("/tvs/scan", response_class=HTMLResponse)
def scan_tvs(request: Request, _: dict[str, Any] = Depends(require_role("admin"))):
    from .dlna import discover_renderers_multi, get_local_ip_for

    existing = {tv["ip"]: tv for tv in store.list_tvs()}
    bind_ips = list(dict.fromkeys([*config.ADVERTISE_HOSTS, get_local_ip_for(next(iter(existing.keys()), "239.255.255.250"))]))
    found = discover_renderers_multi(bind_ips)
    for item in found:
        item["profile"] = detect_profile(item.get("manufacturer"), item.get("model_name"), item.get("friendly_name"))
        item["configured"] = item.get("ip") in existing
    return templates.TemplateResponse(
        "scan.html",
        page_context(request, devices=found, profiles=PROFILES, bind_ips=bind_ips),
    )


@app.post("/tvs/scan/add")
def add_scanned_tv(
    name: str = Form(...),
    ip: str = Form(...),
    profile: str = Form("generic_dlna"),
    control_url: str = Form(""),
    user: dict[str, Any] = Depends(require_role("admin")),
    __: None = Depends(csrf_guard),
):
    ensure_allowed_tv_ip(ip.strip())
    existing = store.get_tv_by_ip(ip.strip())
    if existing:
        store.update_tv_config(
            existing["id"],
            name.strip() or ip.strip(),
            ip.strip(),
            profile_or_default(profile),
            existing.get("active_playlist_id"),
            bool(existing.get("autoplay")),
            control_url.strip(),
        )
        tv_id = existing["id"]
    else:
        tv_id = store.add_tv(name.strip() or ip.strip(), ip.strip(), profile_or_default(profile))
        if control_url.strip():
            store.set_tv_control_url(tv_id, control_url.strip())
    store.add_event(tv_id, "tv_added", f"Added from network scan: {ip}", user["username"])
    return RedirectResponse("/tvs", status_code=303)


@app.post("/tvs/{tv_id}")
def update_tv(
    tv_id: int,
    name: str = Form(...),
    ip: str = Form(...),
    profile: str = Form("generic_dlna"),
    control_url: str = Form(""),
    playlist_id: int = Form(0),
    autoplay: str | None = Form(None),
    user: dict[str, Any] = Depends(require_role("admin")),
    __: None = Depends(csrf_guard),
):
    ensure_allowed_tv_ip(ip.strip())
    store.update_tv_config(
        tv_id,
        name.strip(),
        ip.strip(),
        profile_or_default(profile),
        playlist_id or None,
        autoplay == "on",
        control_url.strip(),
    )
    store.add_event(tv_id, "tv_config_changed", f"Changed TV config {name.strip()}", user["username"])
    return RedirectResponse("/tvs", status_code=303)


@app.post("/tvs/{tv_id}/delete")
def delete_tv(tv_id: int, user: dict[str, Any] = Depends(require_role("admin")), __: None = Depends(csrf_guard)):
    tv = store.get_tv(tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    store.delete_tv(tv_id)
    store.add_event(None, "tv_deleted", f"Deleted TV {tv['name']} / {tv['ip']}", user["username"])
    return RedirectResponse("/tvs", status_code=303)


@app.post("/tvs/{tv_id}/detect")
def detect_tv(tv_id: int, user: dict[str, Any] = Depends(require_role("admin")), __: None = Depends(csrf_guard)):
    from .dlna import discover_device, get_local_ip_for

    tv = store.get_tv(tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    try:
        bind_ip = get_local_ip_for(tv["ip"])
        info = discover_device(tv["ip"], bind_ip)
        profile = detect_profile(info.get("manufacturer"), info.get("model_name"), info.get("friendly_name"))
        store.update_tv_discovery(tv_id, info, profile)
        store.add_event(tv_id, "tv_found", f"Detected {info.get('friendly_name') or tv['ip']}", user["username"])
    except Exception as exc:
        store.set_tv_error(tv_id, str(exc))
        store.add_event(tv_id, "command_failed", "Detect failed", str(exc))
    return RedirectResponse("/tvs", status_code=303)


@app.post("/tvs/{tv_id}/play")
def play_tv(request: Request, tv_id: int, user: dict[str, Any] = Depends(require_role("operator")), __: None = Depends(csrf_guard)):
    ensure_command_rate(request, tv_id)
    store.enqueue_command(tv_id, "play_next")
    store.add_event(tv_id, "manual_skip", "Manual play next", user["username"])
    return RedirectResponse("/", status_code=303)


@app.post("/tvs/{tv_id}/commands/play-next")
def command_play_next(request: Request, tv_id: int, user: dict[str, Any] = Depends(require_role("operator")), __: None = Depends(csrf_guard)):
    ensure_command_rate(request, tv_id)
    store.enqueue_command(tv_id, "play_next")
    store.add_event(tv_id, "manual_skip", "Manual play next", user["username"])
    return RedirectResponse("/", status_code=303)


@app.post("/tvs/{tv_id}/commands/stop")
def command_stop(request: Request, tv_id: int, user: dict[str, Any] = Depends(require_role("operator")), __: None = Depends(csrf_guard)):
    ensure_command_rate(request, tv_id)
    store.enqueue_command(tv_id, "stop")
    store.add_event(tv_id, "manual_stop", "Manual stop", user["username"])
    return RedirectResponse("/", status_code=303)


@app.post("/tvs/{tv_id}/commands/restart-playlist")
def command_restart_playlist(request: Request, tv_id: int, user: dict[str, Any] = Depends(require_role("operator")), __: None = Depends(csrf_guard)):
    ensure_command_rate(request, tv_id)
    store.enqueue_command(tv_id, "restart_playlist")
    store.add_event(tv_id, "manual_restart", "Manual restart playlist", user["username"])
    return RedirectResponse("/", status_code=303)


@app.post("/tvs/{tv_id}/commands/rediscover")
def command_rediscover(request: Request, tv_id: int, user: dict[str, Any] = Depends(require_role("admin")), __: None = Depends(csrf_guard)):
    ensure_command_rate(request, tv_id)
    store.enqueue_command(tv_id, "rediscover")
    store.add_event(tv_id, "manual_rediscover", "Manual rediscover", user["username"])
    return RedirectResponse("/tvs", status_code=303)


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request, _: dict[str, Any] = Depends(require_role("admin"))):
    return templates.TemplateResponse("users.html", page_context(request, users=store.list_users()))


@app.post("/users")
def create_user(
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("viewer"),
    user: dict[str, Any] = Depends(require_role("admin")),
    __: None = Depends(csrf_guard),
):
    if len(password) < 12 and not config.ALLOW_INSECURE_AUTH:
        raise HTTPException(400, "Password must contain at least 12 characters")
    store.create_user(username.strip(), password, role)
    store.add_event(None, "user_created", f"Created user {username.strip()} as {role}", user["username"])
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}")
def update_user(
    user_id: int,
    role: str = Form("viewer"),
    disabled: str | None = Form(None),
    user: dict[str, Any] = Depends(require_role("admin")),
    __: None = Depends(csrf_guard),
):
    if user_id == user["id"] and disabled == "on":
        raise HTTPException(400, "You cannot disable your own user")
    store.update_user(user_id, role, disabled == "on")
    store.add_event(None, "user_updated", f"Updated user {user_id}", user["username"])
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{user_id}/password")
def change_user_password(
    user_id: int,
    password: str = Form(...),
    user: dict[str, Any] = Depends(require_role("admin")),
    __: None = Depends(csrf_guard),
):
    if len(password) < 12 and not config.ALLOW_INSECURE_AUTH:
        raise HTTPException(400, "Password must contain at least 12 characters")
    store.set_user_password(user_id, password)
    store.add_event(None, "user_password_changed", f"Changed password for user {user_id}", user["username"])
    return RedirectResponse("/users", status_code=303)


@app.get("/api/status")
def api_status(_: dict[str, Any] = Depends(require_auth)):
    return {"tvs": store.list_tvs(), "media": store.list_media(), "playlists": store.list_playlists()}


@app.post("/api/v1/auth/login", tags=["auth"], summary="Create a web/API session")
def api_login(request: Request, payload: LoginRequest):
    ip = client_ip(request)
    if rate_limited(_auth_failures, ip, 10, 300):
        store.add_event(None, "login_rate_limited", "API login rate limited", ip)
        raise HTTPException(429, "Too many login attempts")
    user = store.authenticate_user(payload.username, payload.password)
    if not user:
        record_failure(_auth_failures, ip)
        store.add_event(None, "login_failed", f"API login failed for {payload.username}", ip)
        raise HTTPException(401, "Invalid credentials")
    token = store.create_session(user["id"], ip, request.headers.get("user-agent", ""))
    store.add_event(None, "login_success", f"API login success for {user['username']}", ip)
    response = JSONResponse({"user": public_user(user), "csrf_token": create_csrf_token(token)})
    response.set_cookie(
        "screenloop_session",
        token,
        max_age=config.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
    )
    return response


@app.post("/api/v1/auth/logout", tags=["auth"], summary="Destroy the current session")
def api_logout(request: Request, user: dict[str, Any] = Depends(require_api_auth), _: None = Depends(api_csrf_guard)):
    token = request.cookies.get("screenloop_session")
    store.delete_session(token)
    store.add_event(None, "logout", f"API logout {user.get('username')}")
    response = JSONResponse({"ok": True})
    response.delete_cookie("screenloop_session")
    return response


@app.get("/api/v1/session", tags=["auth"], summary="Get current user and CSRF token")
def api_session(request: Request, user: dict[str, Any] = Depends(require_api_auth)):
    return {
        "user": public_user(user),
        "csrf_token": create_csrf_token(request.cookies.get("screenloop_session", "")),
        "roles": ROLE_LEVELS,
    }


@app.get("/api/v1/status", tags=["status"], summary="Get live dashboard state")
def api_v1_status(_: dict[str, Any] = Depends(require_api_auth)):
    return {
        "app": APP_NAME,
        "tvs": store.list_tvs(),
        "media": store.list_media(),
        "playlists": store.list_playlists(),
        "transcode_jobs": store.list_transcode_jobs(),
    }


@app.get("/api/v1/media", tags=["media"], summary="List media")
def api_list_media(_: dict[str, Any] = Depends(require_api_auth)):
    return {"media": store.list_media()}


@app.post("/api/v1/media/upload", tags=["media"], summary="Upload media")
def api_upload_media(
    request: Request,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(require_api_role("operator")),
    _: None = Depends(api_csrf_guard),
):
    upload_key = f"upload:{client_ip(request)}"
    if rate_limited(_action_failures, upload_key, 20, 3600):
        raise HTTPException(429, "Too many uploads")
    record_failure(_action_failures, upload_key)
    media_id = save_upload(file, user)
    return {"id": media_id, "media": store.get_media(media_id)}


@app.delete("/api/v1/media/{media_id}", tags=["media"], summary="Delete media")
def api_delete_media(media_id: int, user: dict[str, Any] = Depends(require_api_role("admin")), _: None = Depends(api_csrf_guard)):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    paths = [media["original_path"], *store.media_output_paths(media_id)]
    store.delete_media(media_id)
    for item in paths:
        unlink_quiet(Path(item))
    store.add_event(None, "media_deleted", f"API deleted media {media_id}", user["username"])
    return {"ok": True}


@app.get("/api/v1/playlists", tags=["playlists"], summary="List playlists")
def api_list_playlists(_: dict[str, Any] = Depends(require_api_auth)):
    return {"playlists": store.list_playlists()}


@app.post("/api/v1/playlists", tags=["playlists"], summary="Create playlist")
def api_create_playlist(payload: PlaylistCreateRequest, user: dict[str, Any] = Depends(require_api_role("operator")), _: None = Depends(api_csrf_guard)):
    playlist_id = store.create_playlist(payload.name.strip())
    store.add_event(None, "playlist_created", f"API created playlist {payload.name.strip()}", user["username"])
    return {"id": playlist_id, "playlist": store.get_playlist(playlist_id)}


@app.get("/api/v1/playlists/{playlist_id}", tags=["playlists"], summary="Get playlist with items")
def api_get_playlist(playlist_id: int, _: dict[str, Any] = Depends(require_api_auth)):
    playlist = playlist_or_404(playlist_id)
    return {"playlist": playlist, "items": store.playlist_items(playlist_id)}


@app.delete("/api/v1/playlists/{playlist_id}", tags=["playlists"], summary="Delete playlist")
def api_delete_playlist(playlist_id: int, user: dict[str, Any] = Depends(require_api_role("admin")), _: None = Depends(api_csrf_guard)):
    playlist = playlist_or_404(playlist_id)
    store.delete_playlist(playlist_id)
    store.add_event(None, "playlist_deleted", f"API deleted playlist {playlist['name']}", user["username"])
    return {"ok": True}


@app.post("/api/v1/playlists/{playlist_id}/items", tags=["playlists"], summary="Add playlist item")
def api_add_playlist_item(
    playlist_id: int,
    payload: PlaylistItemRequest,
    user: dict[str, Any] = Depends(require_api_role("operator")),
    _: None = Depends(api_csrf_guard),
):
    playlist_or_404(playlist_id)
    if not store.get_media(payload.media_id):
        raise HTTPException(404, "Media not found")
    store.add_playlist_item(playlist_id, payload.media_id)
    store.add_event(None, "playlist_item_added", f"API added media {payload.media_id} to playlist {playlist_id}", user["username"])
    return {"ok": True, "items": store.playlist_items(playlist_id)}


@app.delete("/api/v1/playlist-items/{item_id}", tags=["playlists"], summary="Remove playlist item")
def api_delete_playlist_item(item_id: int, user: dict[str, Any] = Depends(require_api_role("operator")), _: None = Depends(api_csrf_guard)):
    store.remove_playlist_item(item_id)
    store.add_event(None, "playlist_item_removed", f"API removed playlist item {item_id}", user["username"])
    return {"ok": True}


@app.post("/api/v1/playlist-items/{item_id}/move", tags=["playlists"], summary="Move playlist item")
def api_move_playlist_item(
    item_id: int,
    payload: PlaylistMoveRequest,
    user: dict[str, Any] = Depends(require_api_role("operator")),
    _: None = Depends(api_csrf_guard),
):
    store.move_playlist_item(item_id, payload.direction)
    store.add_event(None, "playlist_item_moved", f"API moved playlist item {item_id} {payload.direction}", user["username"])
    return {"ok": True}


@app.get("/api/v1/tvs", tags=["tvs"], summary="List TVs and profiles")
def api_list_tvs(_: dict[str, Any] = Depends(require_api_auth)):
    return {"tvs": store.list_tvs(), "profiles": PROFILES}


@app.get("/api/v1/tvs/export", tags=["tvs"], summary="Export TV configs")
def api_export_tvs(_: dict[str, Any] = Depends(require_api_role("admin"))):
    return {
        "version": 1,
        "app": APP_NAME,
        "exported_at": int(time.time()),
        "tvs": store.export_tvs(),
    }


@app.post("/api/v1/tvs/import", tags=["tvs"], summary="Import TV configs")
def api_import_tvs(payload: dict[str, Any], user: dict[str, Any] = Depends(require_api_role("admin")), _: None = Depends(api_csrf_guard)):
    tvs = payload.get("tvs") if isinstance(payload, dict) else None
    if not isinstance(tvs, list):
        raise HTTPException(400, "Import must contain a tvs list")
    for item in tvs:
        if isinstance(item, dict) and item.get("ip"):
            ensure_allowed_tv_ip(str(item["ip"]).strip())
    created, updated = store.import_tvs(tvs)
    store.add_event(None, "tv_import", f"API imported TV configs: {created} created, {updated} updated", user["username"])
    return {"created": created, "updated": updated}


@app.get("/api/v1/tvs/scan", tags=["tvs"], summary="Scan network for TVs")
def api_scan_tvs(_: dict[str, Any] = Depends(require_api_role("admin"))):
    from .dlna import discover_renderers_multi, get_local_ip_for

    existing = {tv["ip"]: tv for tv in store.list_tvs()}
    bind_ips = list(dict.fromkeys([*config.ADVERTISE_HOSTS, get_local_ip_for(next(iter(existing.keys()), "239.255.255.250"))]))
    found = discover_renderers_multi(bind_ips)
    for item in found:
        item["profile"] = detect_profile(item.get("manufacturer"), item.get("model_name"), item.get("friendly_name"))
        item["configured"] = item.get("ip") in existing
    return {"devices": found, "profiles": PROFILES, "bind_ips": bind_ips}


@app.post("/api/v1/tvs", tags=["tvs"], summary="Create TV")
def api_create_tv(payload: TvCreateRequest, user: dict[str, Any] = Depends(require_api_role("admin")), _: None = Depends(api_csrf_guard)):
    ip = payload.ip.strip()
    ensure_allowed_tv_ip(ip)
    tv_id = store.add_tv(payload.name.strip() or ip, ip, profile_or_default(payload.profile))
    store.add_event(tv_id, "tv_added", f"API added TV {ip}", user["username"])
    return {"id": tv_id, "tv": store.get_tv(tv_id)}


@app.patch("/api/v1/tvs/{tv_id}", tags=["tvs"], summary="Update TV")
def api_update_tv(
    tv_id: int,
    payload: TvUpdateRequest,
    user: dict[str, Any] = Depends(require_api_role("admin")),
    _: None = Depends(api_csrf_guard),
):
    tv_or_404(tv_id)
    ip = payload.ip.strip()
    ensure_allowed_tv_ip(ip)
    if payload.playlist_id is not None:
        playlist_or_404(payload.playlist_id)
    store.update_tv_config(
        tv_id,
        payload.name.strip(),
        ip,
        profile_or_default(payload.profile),
        payload.playlist_id,
        payload.autoplay,
        (payload.control_url or "").strip(),
    )
    store.add_event(tv_id, "tv_config_changed", f"API changed TV config {payload.name.strip()}", user["username"])
    return {"ok": True, "tv": store.get_tv(tv_id)}


@app.delete("/api/v1/tvs/{tv_id}", tags=["tvs"], summary="Delete TV")
def api_delete_tv(tv_id: int, user: dict[str, Any] = Depends(require_api_role("admin")), _: None = Depends(api_csrf_guard)):
    tv = tv_or_404(tv_id)
    store.delete_tv(tv_id)
    store.add_event(None, "tv_deleted", f"API deleted TV {tv['name']} / {tv['ip']}", user["username"])
    return {"ok": True}


@app.post("/api/v1/tvs/{tv_id}/detect", tags=["tvs"], summary="Detect TV metadata and control URL")
def api_detect_tv(tv_id: int, user: dict[str, Any] = Depends(require_api_role("admin")), _: None = Depends(api_csrf_guard)):
    from .dlna import discover_device, get_local_ip_for

    tv = tv_or_404(tv_id)
    try:
        bind_ip = get_local_ip_for(tv["ip"])
        info = discover_device(tv["ip"], bind_ip)
        profile = detect_profile(info.get("manufacturer"), info.get("model_name"), info.get("friendly_name"))
        store.update_tv_discovery(tv_id, info, profile)
        store.add_event(tv_id, "tv_found", f"API detected {info.get('friendly_name') or tv['ip']}", user["username"])
    except Exception as exc:
        store.set_tv_error(tv_id, str(exc))
        store.add_event(tv_id, "command_failed", "API detect failed", str(exc))
        raise HTTPException(502, f"Detect failed: {exc}") from exc
    return {"ok": True, "tv": store.get_tv(tv_id)}


@app.post("/api/v1/tvs/{tv_id}/commands", tags=["tvs"], summary="Queue TV playback command")
def api_tv_command(
    request: Request,
    tv_id: int,
    payload: TvCommandRequest,
    user: dict[str, Any] = Depends(require_api_role("operator")),
    _: None = Depends(api_csrf_guard),
):
    tv_or_404(tv_id)
    if payload.command == "rediscover" and ROLE_LEVELS.get(user["role"], 0) < ROLE_LEVELS["admin"]:
        raise HTTPException(403, "Insufficient permissions")
    ensure_command_rate(request, tv_id)
    command_id = store.enqueue_command(tv_id, payload.command)
    store.add_event(tv_id, f"manual_{payload.command}", f"API queued {payload.command}", user["username"])
    return {"ok": True, "command_id": command_id}


@app.get("/api/v1/transcode/jobs", tags=["transcode"], summary="List transcode jobs")
def api_transcode_jobs(_: dict[str, Any] = Depends(require_api_auth)):
    return {"jobs": store.list_transcode_jobs()}


@app.post("/api/v1/transcode/jobs/{job_id}/rebuild", tags=["transcode"], summary="Rebuild transcode job")
def api_rebuild_transcode(job_id: int, user: dict[str, Any] = Depends(require_api_role("operator")), _: None = Depends(api_csrf_guard)):
    store.rebuild_transcode_job(job_id)
    store.add_event(None, "transcode_rebuild", f"API rebuild queued for job {job_id}", user["username"])
    return {"ok": True}


@app.post("/api/v1/transcode/cleanup", tags=["transcode"], summary="Clean stale transcode cache")
def api_cleanup_transcode(user: dict[str, Any] = Depends(require_api_role("admin")), _: None = Depends(api_csrf_guard)):
    referenced = {Path(path) for path in store.referenced_transcode_paths()}
    removed = 0
    for path in config.TRANSCODE_DIR.glob("*"):
        if path.is_file() and path not in referenced:
            unlink_quiet(path)
            removed += 1
    store.add_event(None, "cache_cleanup", f"API removed {removed} stale transcode files", user["username"])
    return {"removed": removed}


@app.get("/api/v1/events", tags=["events"], summary="List service and audit events")
def api_events(
    tv_id: int = 0,
    event_type: str | None = None,
    limit: int = 200,
    _: dict[str, Any] = Depends(require_api_auth),
):
    safe_limit = min(max(limit, 1), 500)
    return {"events": store.list_events(tv_id or None, event_type, safe_limit)}


@app.get("/api/v1/users", tags=["users"], summary="List users")
def api_users(_: dict[str, Any] = Depends(require_api_role("admin"))):
    return {"users": store.list_users()}


@app.post("/api/v1/users", tags=["users"], summary="Create user")
def api_create_user(payload: UserCreateRequest, user: dict[str, Any] = Depends(require_api_role("admin")), _: None = Depends(api_csrf_guard)):
    require_password_strength(payload.password)
    user_id = store.create_user(payload.username.strip(), payload.password, payload.role)
    store.add_event(None, "user_created", f"API created user {payload.username.strip()} as {payload.role}", user["username"])
    return {"id": user_id, "user": store.get_user(user_id)}


@app.patch("/api/v1/users/{user_id}", tags=["users"], summary="Update user role/status")
def api_update_user(
    user_id: int,
    payload: UserUpdateRequest,
    user: dict[str, Any] = Depends(require_api_role("admin")),
    _: None = Depends(api_csrf_guard),
):
    if user_id == user["id"] and payload.disabled:
        raise HTTPException(400, "You cannot disable your own user")
    if not store.get_user(user_id):
        raise HTTPException(404, "User not found")
    store.update_user(user_id, payload.role, payload.disabled)
    store.add_event(None, "user_updated", f"API updated user {user_id}", user["username"])
    return {"ok": True, "user": store.get_user(user_id)}


@app.post("/api/v1/users/{user_id}/password", tags=["users"], summary="Change user password")
def api_change_user_password(
    user_id: int,
    payload: PasswordChangeRequest,
    user: dict[str, Any] = Depends(require_api_role("admin")),
    _: None = Depends(api_csrf_guard),
):
    if not store.get_user(user_id):
        raise HTTPException(404, "User not found")
    require_password_strength(payload.password)
    store.set_user_password(user_id, payload.password)
    store.add_event(None, "user_password_changed", f"API changed password for user {user_id}", user["username"])
    return {"ok": True}


@app.get("/api/health", tags=["health"], summary="Public healthcheck")
def api_health():
    return {"status": "ok", "app": APP_NAME}


@app.get("/transcode", response_class=HTMLResponse)
def transcode_page(request: Request, _: dict[str, Any] = Depends(require_auth)):
    return templates.TemplateResponse(
        "transcode.html",
        page_context(request, jobs=store.list_transcode_jobs()),
    )


@app.post("/transcode/{job_id}/rebuild")
def rebuild_transcode(job_id: int, user: dict[str, Any] = Depends(require_role("operator")), __: None = Depends(csrf_guard)):
    store.rebuild_transcode_job(job_id)
    store.add_event(None, "transcode_rebuild", f"Rebuild queued for job {job_id}", user["username"])
    return RedirectResponse("/transcode", status_code=303)


@app.post("/transcode/cleanup")
def cleanup_transcode(user: dict[str, Any] = Depends(require_role("admin")), __: None = Depends(csrf_guard)):
    referenced = {Path(path) for path in store.referenced_transcode_paths()}
    removed = 0
    for path in config.TRANSCODE_DIR.glob("*"):
        if path.is_file() and path not in referenced:
            unlink_quiet(path)
            removed += 1
    store.add_event(None, "cache_cleanup", f"Removed {removed} stale transcode files", user["username"])
    return RedirectResponse("/transcode", status_code=303)


@app.get("/events", response_class=HTMLResponse)
def events_page(request: Request, _: dict[str, Any] = Depends(require_auth)):
    tv_id = int(request.query_params.get("tv_id", "0") or 0)
    event_type = request.query_params.get("event_type") or None
    return templates.TemplateResponse(
        "events.html",
        page_context(
            request,
            events=store.list_events(tv_id or None, event_type, 300),
            tvs=store.list_tvs(),
            selected_tv_id=tv_id,
            selected_event_type=event_type or "",
        ),
    )


@app.get("/stream/{media_id}")
def stream_media(media_id: int, request: Request, profile: str = "generic_dlna", token: str = ""):
    path = stream_path(media_id, profile, token, request)
    return ranged_file_response(path, request, send_body=True)


@app.head("/stream/{media_id}")
def head_media(media_id: int, request: Request, profile: str = "generic_dlna", token: str = ""):
    path = stream_path(media_id, profile, token, request)
    maybe_advance_replayed_stream(media_id, request)
    return ranged_file_response(path, request, send_body=False)


def stream_path(media_id: int, profile: str, token: str, request: Request) -> Path:
    media = store.get_media(media_id)
    profile = profile_or_default(profile)
    if not verify_stream_token(media_id, profile, token):
        ip = client_ip(request)
        stream_key = f"stream:{ip}"
        if rate_limited(_action_failures, stream_key, 60, 300):
            raise HTTPException(429, "Too many stream token failures")
        record_failure(_action_failures, stream_key)
        store.add_event(None, "stream_denied", f"Denied stream token for media {media_id} / {profile}", ip)
        raise HTTPException(403, "Invalid stream token")
    transcode_row = store.get_transcode(media_id, profile)
    if not media or not transcode_row or transcode_row["status"] != "done" or not transcode_row["output_path"]:
        raise HTTPException(404, "Media is not ready")
    path = Path(transcode_row["output_path"])
    if not path.exists():
        raise HTTPException(404, "Transcoded file not found")
    return path


def maybe_advance_replayed_stream(media_id: int, request: Request) -> None:
    client_host = request.client.host if request.client else ""
    if not client_host:
        return
    tv = store.get_tv_by_ip(client_host)
    if not tv or not tv.get("autoplay") or not tv.get("active_playlist_id"):
        return
    if tv.get("current_media_id") != media_id:
        return

    started_at = int(tv.get("playback_started_at") or 0)
    media = store.get_media(media_id)
    replay_after = replay_after_seconds(media)
    now = time.time()
    if not started_at or now - started_at < replay_after:
        return

    last_advance_at = int(tv.get("last_replay_advance_at") or 0)
    replay_cooldown = max(config.AUTO_ADVANCE_REPLAY_COOLDOWN, replay_after)
    if last_advance_at and now - last_advance_at < replay_cooldown:
        return
    if store.has_active_command(tv["id"], "play_next"):
        return

    items = store.playlist_items(tv["active_playlist_id"])
    if len(items) < 2:
        return

    queued_index = int(tv.get("current_index") or 0)
    if queued_index >= len(items):
        queued_index = 0
    if items[queued_index]["media_id"] == media_id:
        return

    print(f"[web] replay detected tv={tv['id']} media={media_id}; queueing next", flush=True)
    store.add_event(tv["id"], "replay_detected", f"Replay detected for media {media_id}")
    store.mark_tv_replay_advance(tv["id"])
    store.enqueue_command(tv["id"], "play_next")


def replay_after_seconds(media: dict | None) -> int:
    if media and media.get("duration_seconds"):
        return max(config.AUTO_ADVANCE_REPLAY_AFTER, int(float(media["duration_seconds"]) * 0.95))
    return max(config.AUTO_ADVANCE_REPLAY_AFTER, config.AUTO_ADVANCE_UNKNOWN_DURATION_AFTER)


def ranged_file_response(path: Path, request: Request, send_body: bool) -> Response:
    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    start = 0
    end = file_size - 1
    status_code = 200

    if range_header and range_header.startswith("bytes="):
        status_code = 206
        range_value = range_header.replace("bytes=", "", 1)
        start_text, _, end_text = range_value.partition("-")
        if start_text:
            start = int(start_text)
        if end_text:
            end = int(end_text)
        if start > end or start >= file_size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    length = end - start + 1
    headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
        "transferMode.dlna.org": "Streaming",
        "contentFeatures.dlna.org": "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    if not send_body:
        return Response(status_code=status_code, headers=headers)

    def iter_file():
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(iter_file(), status_code=status_code, headers=headers)


def unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def main() -> None:
    import uvicorn

    uvicorn.run("screenloop.web:app", host=config.HTTP_HOST, port=config.HTTP_PORT, access_log=config.ACCESS_LOG)


if __name__ == "__main__":
    main()
