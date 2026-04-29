import hashlib
import secrets
import shutil
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

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
templates.env.globals["default_password"] = config.BASIC_AUTH_PASSWORD in {"", "admin", "change-me", "1234"}
security = HTTPBasic()
app = FastAPI(title=APP_NAME)
_auth_failures: dict[str, deque[float]] = defaultdict(deque)


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
    return {
        "request": request,
        "locale": locale,
        "t": lambda text: translate(locale, text),
        "csrf_token": create_csrf_token(),
        "csrf_field": f'<input type="hidden" name="csrf_token" value="{create_csrf_token()}">',
        **extra,
    }


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def auth_blocked(ip: str) -> bool:
    now = time.time()
    failures = _auth_failures[ip]
    while failures and now - failures[0] > 300:
        failures.popleft()
    return len(failures) >= 10


def record_auth_failure(ip: str) -> None:
    _auth_failures[ip].append(time.time())


def csrf_guard(csrf_token: str = Form("")) -> None:
    if not verify_csrf_token(csrf_token):
        raise HTTPException(403, "Invalid CSRF token")


def require_auth(request: Request, credentials: HTTPBasicCredentials = Depends(security)) -> str:
    ip = client_ip(request)
    if auth_blocked(ip):
        raise HTTPException(429, "Too many authentication failures")
    valid_user = secrets.compare_digest(credentials.username, config.BASIC_AUTH_USER)
    valid_password = secrets.compare_digest(credentials.password, config.BASIC_AUTH_PASSWORD)
    if not (valid_user and valid_password):
        record_auth_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.on_event("startup")
def startup() -> None:
    config.validate_security_config()
    worker.start()


@app.on_event("shutdown")
def shutdown() -> None:
    worker.stop()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _: str = Depends(require_auth)):
    return templates.TemplateResponse(
        "dashboard.html",
        page_context(request, tvs=store.list_tvs(), media=store.list_media(), playlists=store.list_playlists()),
    )


@app.get("/media", response_class=HTMLResponse)
def media_page(request: Request, _: str = Depends(require_auth)):
    return templates.TemplateResponse("media.html", page_context(request, media=store.list_media()))


@app.get("/language/{locale}")
def set_language(locale: str, request: Request, _: str = Depends(require_auth)):
    response = RedirectResponse(request.headers.get("referer") or "/", status_code=303)
    response.set_cookie("screenloop_lang", normalize_locale(locale), httponly=True, samesite="lax")
    return response


@app.post("/media/upload")
def upload_media(
    file: UploadFile = File(...),
    _: str = Depends(require_auth),
    __: None = Depends(csrf_guard),
):
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

    media_id = store.add_media(
        Path(original_name).stem,
        target,
        original_name,
        target.stat().st_size,
        media_digest(target),
        probe_duration_seconds(target),
    )
    for profile in PROFILES:
        store.ensure_transcode_job(media_id, profile)
    return RedirectResponse("/media", status_code=303)


@app.post("/media/{media_id}/delete")
def delete_media(media_id: int, _: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    paths = [media["original_path"], *store.media_output_paths(media_id)]
    store.delete_media(media_id)
    for item in paths:
        unlink_quiet(Path(item))
    store.add_event(None, "media_deleted", f"Deleted media {media_id}")
    return RedirectResponse("/media", status_code=303)


@app.get("/playlists", response_class=HTMLResponse)
def playlists_page(request: Request, _: str = Depends(require_auth)):
    playlists = store.list_playlists()
    selected_id = int(request.query_params.get("id", playlists[0]["id"] if playlists else 0))
    selected = store.playlist_items(selected_id) if selected_id else []
    return templates.TemplateResponse(
        "playlists.html",
        page_context(request, playlists=playlists, selected_id=selected_id, items=selected, media=store.list_media()),
    )


@app.post("/playlists")
def create_playlist(name: str = Form(...), _: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    store.create_playlist(name.strip())
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{playlist_id}/delete")
def delete_playlist(playlist_id: int, _: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    playlist = store.get_playlist(playlist_id)
    if not playlist:
        raise HTTPException(404, "Playlist not found")
    store.delete_playlist(playlist_id)
    store.add_event(None, "playlist_deleted", f"Deleted playlist {playlist['name']}")
    return RedirectResponse("/playlists", status_code=303)


@app.post("/playlists/{playlist_id}/items")
def add_playlist_item(
    playlist_id: int,
    media_id: int = Form(...),
    _: str = Depends(require_auth),
    __: None = Depends(csrf_guard),
):
    store.add_playlist_item(playlist_id, media_id)
    return RedirectResponse(f"/playlists?id={playlist_id}", status_code=303)


@app.post("/playlist-items/{item_id}/delete")
def delete_playlist_item(
    item_id: int,
    playlist_id: int = Form(...),
    _: str = Depends(require_auth),
    __: None = Depends(csrf_guard),
):
    store.remove_playlist_item(item_id)
    return RedirectResponse(f"/playlists?id={playlist_id}", status_code=303)


@app.post("/playlist-items/{item_id}/move")
def move_playlist_item(
    item_id: int,
    playlist_id: int = Form(...),
    direction: str = Form(...),
    _: str = Depends(require_auth),
    __: None = Depends(csrf_guard),
):
    store.move_playlist_item(item_id, direction)
    return RedirectResponse(f"/playlists?id={playlist_id}", status_code=303)


@app.get("/tvs", response_class=HTMLResponse)
def tvs_page(request: Request, _: str = Depends(require_auth)):
    return templates.TemplateResponse(
        "tvs.html",
        page_context(request, tvs=store.list_tvs(), playlists=store.list_playlists(), profiles=PROFILES),
    )


@app.post("/tvs")
def add_tv(
    name: str = Form(...),
    ip: str = Form(...),
    _: str = Depends(require_auth),
    __: None = Depends(csrf_guard),
):
    store.add_tv(name.strip() or ip.strip(), ip.strip(), "generic_dlna")
    return RedirectResponse("/tvs", status_code=303)


@app.get("/tvs/scan", response_class=HTMLResponse)
def scan_tvs(request: Request, _: str = Depends(require_auth)):
    from .dlna import discover_renderers, get_local_ip_for

    existing = {tv["ip"]: tv for tv in store.list_tvs()}
    bind_ip = get_local_ip_for(next(iter(existing.keys()), "239.255.255.250"))
    found = discover_renderers(bind_ip)
    for item in found:
        item["profile"] = detect_profile(item.get("manufacturer"), item.get("model_name"), item.get("friendly_name"))
        item["configured"] = item.get("ip") in existing
    return templates.TemplateResponse(
        "scan.html",
        page_context(request, devices=found, profiles=PROFILES),
    )


@app.post("/tvs/scan/add")
def add_scanned_tv(
    name: str = Form(...),
    ip: str = Form(...),
    profile: str = Form("generic_dlna"),
    control_url: str = Form(""),
    _: str = Depends(require_auth),
    __: None = Depends(csrf_guard),
):
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
    store.add_event(tv_id, "tv_added", f"Added from network scan: {ip}")
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
    _: str = Depends(require_auth),
    __: None = Depends(csrf_guard),
):
    store.update_tv_config(
        tv_id,
        name.strip(),
        ip.strip(),
        profile_or_default(profile),
        playlist_id or None,
        autoplay == "on",
        control_url.strip(),
    )
    return RedirectResponse("/tvs", status_code=303)


@app.post("/tvs/{tv_id}/delete")
def delete_tv(tv_id: int, _: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    tv = store.get_tv(tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    store.delete_tv(tv_id)
    store.add_event(None, "tv_deleted", f"Deleted TV {tv['name']} / {tv['ip']}")
    return RedirectResponse("/tvs", status_code=303)


@app.post("/tvs/{tv_id}/detect")
def detect_tv(tv_id: int, _: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    from .dlna import discover_device, get_local_ip_for

    tv = store.get_tv(tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    try:
        bind_ip = get_local_ip_for(tv["ip"])
        info = discover_device(tv["ip"], bind_ip)
        profile = detect_profile(info.get("manufacturer"), info.get("model_name"), info.get("friendly_name"))
        store.update_tv_discovery(tv_id, info, profile)
        store.add_event(tv_id, "tv_found", f"Detected {info.get('friendly_name') or tv['ip']}")
    except Exception as exc:
        store.set_tv_error(tv_id, str(exc))
        store.add_event(tv_id, "command_failed", "Detect failed", str(exc))
    return RedirectResponse("/tvs", status_code=303)


@app.post("/tvs/{tv_id}/play")
def play_tv(tv_id: int, _: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    store.enqueue_command(tv_id, "play_next")
    return RedirectResponse("/", status_code=303)


@app.post("/tvs/{tv_id}/commands/play-next")
def command_play_next(tv_id: int, _: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    store.enqueue_command(tv_id, "play_next")
    return RedirectResponse("/", status_code=303)


@app.post("/tvs/{tv_id}/commands/stop")
def command_stop(tv_id: int, _: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    store.enqueue_command(tv_id, "stop")
    return RedirectResponse("/", status_code=303)


@app.post("/tvs/{tv_id}/commands/restart-playlist")
def command_restart_playlist(tv_id: int, _: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    store.enqueue_command(tv_id, "restart_playlist")
    return RedirectResponse("/", status_code=303)


@app.post("/tvs/{tv_id}/commands/rediscover")
def command_rediscover(tv_id: int, _: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    store.enqueue_command(tv_id, "rediscover")
    return RedirectResponse("/tvs", status_code=303)


@app.get("/api/status")
def api_status(_: str = Depends(require_auth)):
    return {"tvs": store.list_tvs(), "media": store.list_media(), "playlists": store.list_playlists()}


@app.get("/api/health")
def api_health():
    return {"status": "ok", "app": APP_NAME}


@app.get("/transcode", response_class=HTMLResponse)
def transcode_page(request: Request, _: str = Depends(require_auth)):
    return templates.TemplateResponse(
        "transcode.html",
        page_context(request, jobs=store.list_transcode_jobs()),
    )


@app.post("/transcode/{job_id}/rebuild")
def rebuild_transcode(job_id: int, _: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    store.rebuild_transcode_job(job_id)
    store.add_event(None, "transcode_rebuild", f"Rebuild queued for job {job_id}")
    return RedirectResponse("/transcode", status_code=303)


@app.post("/transcode/cleanup")
def cleanup_transcode(_: str = Depends(require_auth), __: None = Depends(csrf_guard)):
    referenced = {Path(path) for path in store.referenced_transcode_paths()}
    removed = 0
    for path in config.TRANSCODE_DIR.glob("*"):
        if path.is_file() and path not in referenced:
            unlink_quiet(path)
            removed += 1
    store.add_event(None, "cache_cleanup", f"Removed {removed} stale transcode files")
    return RedirectResponse("/transcode", status_code=303)


@app.get("/events", response_class=HTMLResponse)
def events_page(request: Request, _: str = Depends(require_auth)):
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
    path = stream_path(media_id, profile, token)
    return ranged_file_response(path, request, send_body=True)


@app.head("/stream/{media_id}")
def head_media(media_id: int, request: Request, profile: str = "generic_dlna", token: str = ""):
    path = stream_path(media_id, profile, token)
    maybe_advance_replayed_stream(media_id, request)
    return ranged_file_response(path, request, send_body=False)


def stream_path(media_id: int, profile: str, token: str) -> Path:
    media = store.get_media(media_id)
    profile = profile_or_default(profile)
    if not verify_stream_token(media_id, profile, token):
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

    uvicorn.run("screenloop.web:app", host=config.HTTP_HOST, port=config.HTTP_PORT)


if __name__ == "__main__":
    main()
