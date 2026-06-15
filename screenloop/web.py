import asyncio
import hashlib
import ipaddress
import json
import os
import platform
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import APP_AUTHOR, APP_NAME, APP_REPOSITORY, APP_REVISION, APP_VERSION
from . import config
from .dlna import set_next_uri
from .events import elapsed_seconds, event_details, parse_event_details
from .profiles import PROFILES, detect_profile, profile_or_default
from .security import create_csrf_token, verify_csrf_token, verify_stream_token
from .store import Store
from .transcode import VIDEO_EXTENSIONS, media_digest, probe_duration_seconds
from .worker import Worker, stream_url_for_tv


config.ensure_dirs()
store = Store()
worker = Worker(store)
FRONTEND_DIST = Path(__file__).parent / "static" / "ui"
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
    {"name": "diagnostics", "description": "Admin-only runtime diagnostics without secrets."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup()
    try:
        yield
    finally:
        shutdown()


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION.removeprefix("v"),
    summary="Local TV playlist daemon and DLNA control API.",
    description=(
        "Screenloop controls local TVs and signage screens over DLNA/UPnP. "
        "The `/api/v1` API powers the Vue web UI and trusted LAN integrations. "
        "Authentication uses an HttpOnly `screenloop_session` cookie. Unsafe methods require "
        "`X-CSRF-Token`, retrieved from `/api/v1/session` or `/api/v1/auth/login`."
    ),
    openapi_tags=API_TAGS,
    lifespan=lifespan,
)
if (FRONTEND_DIST / "assets").exists():
    app.mount("/ui/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="ui-assets")
_auth_failures: dict[str, deque[float]] = defaultdict(deque)
_action_failures: dict[str, deque[float]] = defaultdict(deque)
_stream_revocations: dict[str, float] = {}
_stream_advance_timers: dict[int, threading.Timer] = {}
_stream_timer_lock = threading.Lock()
_version_cache: dict[str, Any] = {"checked_at": 0, "latest_version": None, "error": None}
ROLE_LEVELS = {"viewer": 1, "operator": 2, "admin": 3}
RoleName = Literal["admin", "operator", "viewer"]
TvCommandName = Literal["play_next", "stop", "restart_playlist", "rediscover", "mute", "unmute"]


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


class MediaSilentRequest(BaseModel):
    silent: bool


class MediaCompressionRequest(BaseModel):
    compressed: bool


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


def normalize_version(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    text = value.strip().removeprefix("v").split("-", 1)[0]
    parts = text.split(".")
    if len(parts) < 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def update_available(current: str, latest: str | None) -> bool:
    current_version = normalize_version(current)
    latest_version = normalize_version(latest)
    if not current_version or not latest_version:
        return False
    return latest_version > current_version


def latest_release_version() -> dict[str, Any]:
    if not config.UPDATE_CHECK:
        return {"enabled": False, "latest_version": None, "update_available": False, "error": None}
    now = time.time()
    if now - float(_version_cache.get("checked_at") or 0) > config.UPDATE_CHECK_INTERVAL_SECONDS:
        try:
            request = urllib.request.Request(
                config.UPDATE_CHECK_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "Screenloop update check"},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            _version_cache.update(
                {
                    "checked_at": now,
                    "latest_version": str(payload.get("tag_name") or payload.get("name") or "").strip() or None,
                    "error": None,
                }
            )
        except Exception as exc:
            _version_cache.update({"checked_at": now, "latest_version": None, "error": str(exc)})
    latest = _version_cache.get("latest_version")
    return {
        "enabled": True,
        "latest_version": latest,
        "update_available": update_available(APP_VERSION, latest),
        "error": _version_cache.get("error"),
    }


def revoke_stream_for_ip(ip: str | None) -> None:
    if ip:
        _stream_revocations[ip] = time.time() + 5 * 60


def allow_stream_for_ip(ip: str | None) -> None:
    if ip:
        _stream_revocations.pop(ip, None)


def stream_revoked(ip: str | None) -> bool:
    if not ip:
        return False
    expires_at = _stream_revocations.get(ip)
    if not expires_at:
        return False
    if expires_at < time.time():
        _stream_revocations.pop(ip, None)
        return False
    return True


def stop_tv_before_delete(tv: dict[str, Any], actor: str, source: str = "web") -> None:
    revoke_stream_for_ip(tv.get("ip"))
    control_url = (tv.get("control_url") or "").strip()
    if not control_url:
        store.add_event(tv["id"], "tv_stop_skipped", f"{source} delete: no control URL for stop", actor)
        return
    try:
        from .dlna import stop_strict

        stop_strict(control_url)
        store.add_event(tv["id"], "tv_stop", f"{source} delete: stop sent before deletion", actor)
    except Exception as exc:
        store.add_event(tv["id"], "tv_stop_failed", f"{source} delete: stop failed before deletion", str(exc))


def run_probe(command: list[str], timeout: int = 3) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "output": (result.stdout or result.stderr).strip().splitlines()[:8],
        }
    except FileNotFoundError:
        return {"ok": False, "returncode": None, "output": ["not installed"]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": None, "output": ["timeout"]}
    except Exception as exc:
        return {"ok": False, "returncode": None, "output": [str(exc)]}


def running_in_container() -> bool:
    if os.environ.get("SCREENLOOP_CONTAINER"):
        return True
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore")
        return any(marker in cgroup for marker in ("docker", "containerd", "kubepods", "podman"))
    except OSError:
        return False


def host_managed_probe(tool_name: str) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "host_managed",
        "returncode": None,
        "output": [f"{tool_name} is managed on the host; CLI is intentionally not installed in the Screenloop container"],
    }


def docker_probe(command: list[str], tool_name: str) -> dict[str, Any]:
    probe = run_probe(command, timeout=3)
    if not probe["ok"] and running_in_container() and probe.get("output") == ["not installed"]:
        return host_managed_probe(tool_name)
    return probe


def directory_size(path: Path, max_files: int = 20_000) -> dict[str, Any]:
    total = 0
    files = 0
    truncated = False
    try:
        if path.is_file():
            return {"bytes": path.stat().st_size, "files": 1, "truncated": False, "exists": True}
        if not path.exists():
            return {"bytes": 0, "files": 0, "truncated": False, "exists": False}
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
                files += 1
                if files >= max_files:
                    truncated = True
                    break
    except OSError:
        truncated = True
    return {"bytes": total, "files": files, "truncated": truncated, "exists": path.exists()}


def disk_snapshot(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path if path.exists() else path.parent)
        return {"total": usage.total, "used": usage.used, "free": usage.free}
    except OSError as exc:
        return {"error": str(exc)}


def network_interfaces() -> list[dict[str, Any]]:
    probe = run_probe(["ip", "-o", "addr", "show", "scope", "global"], timeout=2)
    interfaces: list[dict[str, Any]] = []
    if probe["ok"]:
        for line in probe["output"]:
            parts = line.split()
            if len(parts) >= 4:
                interfaces.append({"name": parts[1], "family": parts[2], "address": parts[3]})
    if interfaces:
        return interfaces
    try:
        return [{"name": name, "family": "unknown", "address": ""} for _, name in socket.if_nameindex()]
    except OSError:
        return []


def worker_snapshot() -> dict[str, Any]:
    return {
        "command_worker": bool(worker._thread and worker._thread.is_alive()),
        "poll_worker": bool(worker._poll_thread and worker._poll_thread.is_alive()),
        "transcode_worker": bool(worker._transcode_thread and worker._transcode_thread.is_alive()),
    }


def diagnostics_snapshot() -> dict[str, Any]:
    jobs = store.list_transcode_jobs()
    command_statuses = store.rows("SELECT status, COUNT(*) AS count FROM tv_commands GROUP BY status ORDER BY status")
    event_count = store.row("SELECT COUNT(*) AS count FROM events") or {"count": 0}
    session_count = store.row("SELECT COUNT(*) AS count FROM sessions WHERE expires_at >= ?", (int(time.time()),)) or {"count": 0}
    media = store.list_media()
    playlists = store.list_playlists()
    tvs = store.list_tvs()
    paths = {
        "data_dir": str(config.DATA_DIR),
        "db_path": str(config.DB_PATH),
        "media_dir": str(config.MEDIA_DIR),
        "transcode_dir": str(config.TRANSCODE_DIR),
    }
    return {
        "app": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "revision": APP_REVISION[:12],
            "author": APP_AUTHOR,
            "repository": APP_REPOSITORY,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "hostname": socket.gethostname(),
        },
        "workers": worker_snapshot(),
        "counts": {
            "media": len(media),
            "playlists": len(playlists),
            "tvs": len(tvs),
            "transcode_jobs": len(jobs),
            "events": int(event_count["count"]),
            "active_sessions": int(session_count["count"]),
        },
        "transcode_statuses": sorted(
            [{"status": status, "count": sum(1 for job in jobs if job["status"] == status)} for status in {job["status"] for job in jobs}],
            key=lambda item: item["status"],
        ),
        "command_statuses": command_statuses,
        "paths": paths,
        "storage": {
            "data_disk": disk_snapshot(config.DATA_DIR),
            "media_dir": directory_size(config.MEDIA_DIR),
            "transcode_dir": directory_size(config.TRANSCODE_DIR),
            "database": directory_size(config.DB_PATH),
        },
        "network": {
            "advertise_hosts": config.ADVERTISE_HOSTS,
            "trusted_proxy_cidrs": config.TRUSTED_PROXY_CIDRS,
            "allowed_tv_cidrs": config.ALLOWED_TV_CIDRS,
            "interfaces": network_interfaces(),
        },
        "probes": {
            "ffmpeg": run_probe(["ffmpeg", "-version"], timeout=3),
            "docker": docker_probe(["docker", "version", "--format", "{{.Server.Version}}"], "docker"),
            "docker_compose": docker_probe(["docker", "compose", "version"], "docker compose"),
        },
        "config": {
            "http_host": config.HTTP_HOST,
            "http_port": config.HTTP_PORT,
            "cookie_secure": config.COOKIE_SECURE,
            "access_log": config.ACCESS_LOG,
            "update_check": config.UPDATE_CHECK,
            "poll_loop_interval": config.POLL_LOOP_INTERVAL,
            "ping_poll": config.PING_POLL,
            "offline_poll": config.OFFLINE_POLL,
            "online_poll": config.ONLINE_POLL,
            "ssdp_timeout": config.SSDP_TIMEOUT,
            "auto_advance_replay_after": config.AUTO_ADVANCE_REPLAY_AFTER,
            "auto_advance_end_grace": config.AUTO_ADVANCE_END_GRACE,
            "auto_advance_replay_cooldown": config.AUTO_ADVANCE_REPLAY_COOLDOWN,
            "push_cooldown": config.PUSH_COOLDOWN,
            "soap_timeout": config.SOAP_TIMEOUT,
            "soap_next_timeout": config.SOAP_NEXT_TIMEOUT,
            "preload_next_uri": config.PRELOAD_NEXT_URI,
            "max_upload_bytes": config.MAX_UPLOAD_BYTES,
        },
    }


def live_snapshot() -> dict[str, Any]:
    return {
        "server_time": int(time.time()),
        "status": {
            "tvs": store.list_tvs(),
            "media": store.list_media(),
            "playlists": store.list_playlists(),
            "transcode_jobs": store.list_transcode_jobs(),
        },
        "events": store.list_events(limit=80),
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
    if len(password) < config.MIN_PASSWORD_LENGTH and not config.ALLOW_INSECURE_AUTH:
        raise HTTPException(400, f"Password must contain at least {config.MIN_PASSWORD_LENGTH} characters")


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


def startup() -> None:
    config.validate_security_config()
    if store.user_count() == 0:
        config.validate_bootstrap_password()
    created = store.ensure_bootstrap_admin(config.BOOTSTRAP_USER, config.BOOTSTRAP_PASSWORD)
    if created:
        store.add_event(None, "security_bootstrap", f"Created bootstrap admin {config.BOOTSTRAP_USER}")
    store.cleanup_sessions()
    store.fail_running_commands()
    worker.start()


def shutdown() -> None:
    worker.stop()


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


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
@app.get("/media", response_class=HTMLResponse, include_in_schema=False)
@app.get("/playlists", response_class=HTMLResponse, include_in_schema=False)
@app.get("/tvs", response_class=HTMLResponse, include_in_schema=False)
@app.get("/transcode", response_class=HTMLResponse, include_in_schema=False)
@app.get("/events", response_class=HTMLResponse, include_in_schema=False)
@app.get("/users", response_class=HTMLResponse, include_in_schema=False)
@app.get("/diagnostics", response_class=HTMLResponse, include_in_schema=False)
@app.get("/settings", response_class=HTMLResponse, include_in_schema=False)
@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
@app.get("/ui/{path:path}", response_class=HTMLResponse, include_in_schema=False)
def vue_ui(path: str = ""):
    index_path = FRONTEND_DIST / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "Vue UI is not built in this image")
    return FileResponse(index_path)


@app.get("/api/v1/session", tags=["auth"], summary="Get current user and CSRF token")
def api_session(request: Request, user: dict[str, Any] = Depends(require_api_auth)):
    return {
        "user": public_user(user),
        "csrf_token": create_csrf_token(request.cookies.get("screenloop_session", "")),
        "roles": ROLE_LEVELS,
    }


@app.get("/api/v1/version", tags=["health"], summary="Get application version and update state")
def api_v1_version(_: dict[str, Any] = Depends(require_api_auth)):
    update = latest_release_version()
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "revision": APP_REVISION[:12],
        "author": APP_AUTHOR,
        "repository": APP_REPOSITORY,
        **update,
    }


@app.get("/api/v1/diagnostics", tags=["diagnostics"], summary="Get admin diagnostics without secrets")
def api_v1_diagnostics(_: dict[str, Any] = Depends(require_api_role("admin"))):
    return diagnostics_snapshot()


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


@app.post("/api/v1/media/{media_id}/silent", tags=["media"], summary="Toggle silent audio for media")
def api_set_media_silent(
    media_id: int,
    payload: MediaSilentRequest,
    user: dict[str, Any] = Depends(require_api_role("operator")),
    _: None = Depends(api_csrf_guard),
):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    if bool(media.get("silent")) != payload.silent:
        store.set_media_silent(media_id, payload.silent)
        store.requeue_transcode_jobs_for_media(media_id)
        label = "media_silent_on" if payload.silent else "media_silent_off"
        store.add_event(None, label, f"API {'silenced' if payload.silent else 'restored audio for'} media {media_id}", user["username"])
    return {"ok": True, "media": store.get_media(media_id)}


@app.post("/api/v1/media/{media_id}/compressed", tags=["media"], summary="Toggle smaller ffmpeg transcodes for media")
def api_set_media_compressed(
    media_id: int,
    payload: MediaCompressionRequest,
    user: dict[str, Any] = Depends(require_api_role("operator")),
    _: None = Depends(api_csrf_guard),
):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    if bool(media.get("compressed")) != payload.compressed:
        store.set_media_compressed(media_id, payload.compressed)
        store.requeue_transcode_jobs_for_media(media_id)
        label = "media_compression_on" if payload.compressed else "media_compression_off"
        store.add_event(
            None,
            label,
            f"API {'enabled smaller transcodes for' if payload.compressed else 'restored standard transcodes for'} media {media_id}",
            user["username"],
        )
    return {"ok": True, "media": store.get_media(media_id)}


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
    allow_stream_for_ip(ip)
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
    previous_tv = tv_or_404(tv_id)
    ip = payload.ip.strip()
    ensure_allowed_tv_ip(ip)
    if previous_tv.get("ip") != ip:
        revoke_stream_for_ip(previous_tv.get("ip"))
    allow_stream_for_ip(ip)
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
    stop_tv_before_delete(tv, user["username"], "api")
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


@app.get("/api/v1/stream/events", tags=["events"], summary="Stream live status and service events with SSE")
async def api_event_stream(request: Request, _: dict[str, Any] = Depends(require_api_auth)):
    session_token = request.cookies.get("screenloop_session")

    async def stream():
        while True:
            if await request.is_disconnected():
                break
            if not store.get_session_user(session_token, touch=False):
                break
            snapshot = live_snapshot()
            payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
            yield f"event: snapshot\ndata: {payload}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}


@app.get("/stream/{media_id}")
def stream_media(media_id: int, request: Request, profile: str = "generic_dlna", token: str = ""):
    path = stream_path(media_id, profile, token, request)
    file_size = path.stat().st_size
    byte_range = parse_range_header(request.headers.get("range"), file_size)
    sync_tv_playback_from_stream(media_id, request.client.host if request.client else "", request.method)
    maybe_advance_replayed_stream(media_id, request, range_end=byte_range[1] if byte_range else None, file_size=file_size)
    return ranged_file_response(path, request, send_body=True)


@app.head("/stream/{media_id}")
def head_media(media_id: int, request: Request, profile: str = "generic_dlna", token: str = ""):
    path = stream_path(media_id, profile, token, request)
    maybe_advance_replayed_stream(media_id, request)
    return ranged_file_response(path, request, send_body=False)


def sync_tv_playback_from_stream(media_id: int, client_host: str, method: str) -> bool:
    if method.upper() != "GET" or not client_host:
        return False
    tv = store.get_tv_by_ip(client_host)
    if not tv or not tv.get("active_playlist_id"):
        return False
    items = store.playlist_items(tv["active_playlist_id"])
    match_index = next((index for index, item in enumerate(items) if item["media_id"] == media_id), None)
    if match_index is None:
        return False

    next_index = advance_playlist_index(match_index, len(items), tv.get("repeat_mode"))
    state = str(tv.get("playback_state") or "")
    media_changed = tv.get("current_media_id") != media_id
    index_changed = int(tv.get("current_index") or 0) != next_index
    start_missing = not tv.get("playback_started_at")
    non_playing = state not in {"PLAYING", "TRANSITIONING"}
    needs_sync = any(
        (
            media_changed,
            index_changed,
            start_missing,
            non_playing,
            bool(tv.get("last_error")),
            not bool(tv.get("online")),
            not bool(tv.get("streaming")),
        )
    )
    if not needs_sync:
        return False

    reset_started = bool(media_changed or start_missing or state == "ERROR")
    now = time.time()
    duration = current_media_duration(media_id)
    push_event = transition_event(tv["id"], "push_media", media_id)
    push_delay = elapsed_seconds(push_event.get("created_at") if push_event else None, now)
    timer_delay = duration + config.AUTO_ADVANCE_END_GRACE if duration > 0 else None
    store.mark_tv_stream_playback(tv["id"], next_index, media_id, reset_started=reset_started)
    sync_event_id = 0
    if media_changed or non_playing or tv.get("last_error") or not tv.get("streaming"):
        sync_event_id = store.add_event(
            tv["id"],
            "stream_playback_sync",
            f"TV requested media {media_id}",
            event_details(
                media_id=media_id,
                state=state or "UNKNOWN",
                reset_started=int(reset_started),
                current_index=match_index,
                next_index=next_index,
                push_event_id=push_event.get("id") if push_event else None,
                push_delay_s=push_delay,
                duration_s=duration or None,
                timer_delay_s=timer_delay,
            ),
        )
    if media_changed or reset_started:
        preload_following_uri_async(tv["id"], media_id, sync_event_id or None)
        schedule_stream_auto_advance(tv["id"], media_id, duration)
    return True


def advance_playlist_index(index: int, total: int, repeat_mode: str | None) -> int:
    next_index = index + 1
    if next_index >= total:
        return 0 if repeat_mode == "all" else total
    return next_index


def current_media_duration(media_id: int) -> int:
    media = store.get_media(media_id)
    try:
        return int(float(media.get("duration_seconds") or 0)) if media else 0
    except (TypeError, ValueError):
        return 0


def transition_event(tv_id: int, event_type: str, media_id: int) -> dict[str, Any] | None:
    for event in store.list_events(tv_id, event_type, limit=40):
        if parse_event_details(event.get("details")).get("media_id") == str(media_id):
            return event
    return None


def preload_following_uri_async(tv_id: int, current_media_id: int, sync_event_id: int | None = None) -> None:
    thread = threading.Thread(
        target=preload_following_uri,
        args=(tv_id, current_media_id, sync_event_id),
        name=f"screenloop-preload-next-{tv_id}",
        daemon=True,
    )
    thread.start()


def preload_following_uri(tv_id: int, current_media_id: int, sync_event_id: int | None = None) -> bool:
    tv = store.get_tv(tv_id)
    if not tv or tv.get("current_media_id") != current_media_id or not tv.get("active_playlist_id"):
        return False
    control_url = (tv.get("control_url") or "").strip()
    if not control_url:
        return False
    items = store.playlist_items(tv["active_playlist_id"])
    current_index = next((index for index, item in enumerate(items) if item["media_id"] == current_media_id), None)
    if current_index is None or len(items) < 2:
        return False
    next_index = advance_playlist_index(current_index, len(items), tv.get("repeat_mode"))
    if next_index >= len(items):
        return False

    item = items[next_index]
    profile_key = profile_or_default(tv.get("profile"))
    profile = PROFILES[profile_key]
    mime_type = str(profile.get("mime_type") or "video/mp4")
    media_url = stream_url_for_tv(tv["ip"], item["media_id"], profile_key)
    started_at = time.time()
    sync_event = store.get_event(sync_event_id) if sync_event_id else transition_event(tv_id, "stream_playback_sync", current_media_id)
    try:
        set_next_uri(
            control_url,
            media_url,
            item["title"],
            mime_type,
            protocol_info=profile.get("dlna_protocol_info"),
        )
        store.add_event(
            tv_id,
            "preload_next_uri",
            f"Preloaded next media {item['media_id']}",
            event_details(
                source="stream_sync",
                media_id=current_media_id,
                target_media_id=item["media_id"],
                stream_sync_event_id=sync_event.get("id") if sync_event else None,
                preload_delay_s=elapsed_seconds(sync_event.get("created_at") if sync_event else started_at, time.time()),
            ),
        )
        return True
    except Exception as exc:
        store.add_event(
            tv_id,
            "preload_next_failed",
            f"Preload next media {item['media_id']} failed",
            event_details(
                source="stream_sync",
                media_id=current_media_id,
                target_media_id=item["media_id"],
                stream_sync_event_id=sync_event.get("id") if sync_event else None,
                preload_delay_s=elapsed_seconds(sync_event.get("created_at") if sync_event else started_at, time.time()),
                error=exc,
            ),
        )
        return False


def schedule_stream_auto_advance(tv_id: int, media_id: int, duration: int) -> None:
    if duration <= 0:
        return
    tv = store.get_tv(tv_id)
    started_at = int(tv.get("playback_started_at") or 0) if tv else 0
    if not started_at:
        return
    delay = max(1.0, float(duration + config.AUTO_ADVANCE_END_GRACE))
    timer = threading.Timer(delay, enqueue_stream_auto_advance, args=(tv_id, media_id, started_at, duration))
    timer.daemon = True
    with _stream_timer_lock:
        previous = _stream_advance_timers.pop(tv_id, None)
        if previous:
            previous.cancel()
        _stream_advance_timers[tv_id] = timer
    timer.start()


def enqueue_stream_auto_advance(tv_id: int, media_id: int, started_at: int, duration: int) -> bool:
    tv = store.get_tv(tv_id)
    now = time.time()
    with _stream_timer_lock:
        _stream_advance_timers.pop(tv_id, None)
    if not tv or not tv.get("autoplay") or not tv.get("active_playlist_id"):
        return False
    if tv.get("current_media_id") != media_id:
        return False
    if int(tv.get("playback_started_at") or 0) != started_at:
        return False
    if store.has_active_command(tv_id, "play_next"):
        return False
    store.add_event(
        tv_id,
        "duration_elapsed",
        f"Playback duration elapsed for media {media_id}",
        event_details(
            source="stream_timer",
            media_id=media_id,
            duration_s=duration,
            timer_delay_s=duration + config.AUTO_ADVANCE_END_GRACE,
            fired_after_s=elapsed_seconds(started_at, now),
            late_by_s=round(max(0.0, now - started_at - duration - config.AUTO_ADVANCE_END_GRACE), 3),
        ),
    )
    store.mark_tv_replay_advance(tv_id)
    store.enqueue_command(tv_id, "play_next")
    return True


def stream_path(media_id: int, profile: str, token: str, request: Request) -> Path:
    stream_client = request.client.host if request.client else ""
    if stream_revoked(stream_client):
        raise HTTPException(410, "TV stream was stopped")
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


def maybe_advance_replayed_stream(
    media_id: int,
    request: Request,
    range_end: int | None = None,
    file_size: int | None = None,
) -> None:
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
    if not started_at:
        return
    near_stream_end = range_end is not None and file_size is not None and stream_range_near_end(range_end, file_size)
    minimum_elapsed = max(config.AUTO_ADVANCE_REPLAY_AFTER, int(replay_after * 0.9)) if near_stream_end else replay_after
    if now - started_at < minimum_elapsed:
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

    event_type = "stream_end_detected" if near_stream_end else "replay_detected"
    message = f"Stream end detected for media {media_id}" if near_stream_end else f"Replay detected for media {media_id}"
    print(f"[web] {event_type} tv={tv['id']} media={media_id}; queueing next", flush=True)
    store.add_event(tv["id"], event_type, message)
    store.mark_tv_replay_advance(tv["id"])
    store.enqueue_command(tv["id"], "play_next")


def replay_after_seconds(media: dict | None) -> int:
    if media and media.get("duration_seconds"):
        return max(config.AUTO_ADVANCE_REPLAY_AFTER, int(float(media["duration_seconds"]) * 0.95))
    return max(config.AUTO_ADVANCE_REPLAY_AFTER, config.AUTO_ADVANCE_UNKNOWN_DURATION_AFTER)


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    if not range_header or not range_header.startswith("bytes="):
        return None
    range_value = range_header.replace("bytes=", "", 1)
    start_text, _, end_text = range_value.partition("-")
    if not start_text:
        return None
    try:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1
    except ValueError:
        return None
    if start > end or start >= file_size:
        return None
    return start, min(end, file_size - 1)


def stream_range_near_end(range_end: int, file_size: int) -> bool:
    if file_size <= 0:
        return False
    margin = max(2 * 1024 * 1024, int(file_size * 0.02))
    return range_end >= max(0, file_size - margin)


def ranged_file_response(path: Path, request: Request, send_body: bool) -> Response:
    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    start = 0
    end = file_size - 1
    status_code = 200

    if range_header and range_header.startswith("bytes="):
        status_code = 206
        byte_range = parse_range_header(range_header, file_size)
        if not byte_range:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
        start, end = byte_range

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
        stream_client = request.client.host if request.client else ""
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                if stream_revoked(stream_client):
                    break
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
