import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import platform
import secrets
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (
    APP_AUTHOR,
    APP_NAME,
    APP_REPOSITORY,
    APP_REVISION,
    APP_VERSION,
    config,
    lifecycle,
    permissions,
    schedule,
)
from .dlna import set_next_uri
from .events import elapsed_seconds, event_details, parse_event_details
from .node_hub import hub as node_hub
from .profiles import (
    DEFAULT_PROFILE,
    MAX_TEMPLATE_BYTES,
    PROFILES,
    TemplateError,
    delete_template,
    detect_profile,
    fetch_template,
    id_from_url,
    install_template,
    profile_or_default,
    public_profile,
    reload_profiles,
)
from .security import create_csrf_token, verify_csrf_token, verify_password, verify_stream_token
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
    {"name": "profiles", "description": "Installed TV templates and community template management."},
    {"name": "groups", "description": "TV group tree used to organise screens by site, floor, or zone."},
    {"name": "events", "description": "Audit and service event log."},
    {"name": "nodes", "description": "Remote node registration, transport, and media sync."},
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
    docs_url="/docs" if config.API_DOCS else None,
    redoc_url="/redoc" if config.API_DOCS else None,
    openapi_url="/openapi.json" if config.API_DOCS else None,
)
if (FRONTEND_DIST / "assets").exists():
    app.mount("/ui/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="ui-assets")
_auth_failures: dict[str, deque[float]] = defaultdict(deque)
_action_failures: dict[str, deque[float]] = defaultdict(deque)
_stream_revocations: dict[str, float] = {}
_stream_advance_timers: dict[int, threading.Timer] = {}
_stream_timer_lock = threading.Lock()
_version_cache: dict[str, Any] = {"checked_at": 0, "latest_version": None, "error": None}
_catalog_cache: dict[str, Any] = {"checked_at": 0, "entries": [], "error": None}
logger = logging.getLogger("screenloop.web")
RoleName = Literal["admin", "operator", "viewer"]
TvCommandName = Literal["play_next", "stop", "restart_playlist", "rediscover", "mute", "unmute"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class TvCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    ip: str = Field(min_length=1, max_length=128)
    profile: str = "generic_dlna"
    node_id: int | None = None
    group_id: int | None = None


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    parent_id: int | None = None
    schedule_mode: str = schedule.INHERIT
    schedule_days: str | None = None
    schedule_start: str | None = None
    schedule_end: str | None = None


class GroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    parent_id: int | None = None
    move: bool = False
    schedule_mode: str | None = None
    schedule_days: str | None = None
    schedule_start: str | None = None
    schedule_end: str | None = None


class TvUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    ip: str = Field(min_length=1, max_length=128)
    profile: str = "generic_dlna"
    playlist_id: int | None = None
    autoplay: bool = True
    control_url: str | None = None
    node_id: int | None = None
    group_id: int | None = None
    schedule_mode: str = schedule.INHERIT
    schedule_days: str | None = None
    schedule_start: str | None = None
    schedule_end: str | None = None


class RoleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=280)
    permissions: list[str] = Field(default_factory=list)


class RoleAssignmentRequest(BaseModel):
    role_id: int
    scope_type: str = permissions.GLOBAL
    scope_id: int | None = None


class UserRolesRequest(BaseModel):
    assignments: list[RoleAssignmentRequest] = Field(default_factory=list)


class OwnerRequest(BaseModel):
    """Where a clip or playlist lives. `null` means the shared library."""

    group_id: int | None = None


class MediaDefaultsRequest(BaseModel):
    silent: bool = False
    compressed: bool = False


class ScheduleRequest(BaseModel):
    enabled: bool = False
    days: str = "0,1,2,3,4"
    start: str = "08:00"
    end: str = "20:00"


class NodeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class NodeRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class NodeEnrollRequest(BaseModel):
    enroll_token: str = Field(min_length=8, max_length=256)


class TvCommandRequest(BaseModel):
    command: TvCommandName


class ProfileInstallRequest(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    catalog_id: str | None = Field(default=None, max_length=40)
    profile_id: str | None = Field(default=None, max_length=40)


class MediaUpdateRequest(BaseModel):
    """Editable properties of a clip. Moving it between zones is a separate
    endpoint: it changes who can see the clip, not how it plays."""

    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    silent: bool | None = None
    compressed: bool | None = None
    # Unix seconds, or null for "never". Omitting the field leaves the current
    # expiry alone; sending null clears it. The state itself is not editable
    # here -- publishing and archiving are permissions of their own.
    expires_at: int | None = Field(default=None, ge=0)


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


class PlaylistPositionRequest(BaseModel):
    position: int = Field(ge=0, le=10_000)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)
    role: RoleName = "viewer"


class UserUpdateRequest(BaseModel):
    role: RoleName
    disabled: bool = False


class PasswordChangeRequest(BaseModel):
    password: str = Field(min_length=1, max_length=512)
    admin_password: str = Field(min_length=1, max_length=512)


class SelfPasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=1, max_length=512)


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


MAX_CATALOG_BYTES = 512 * 1024


def parse_catalog(payload: Any) -> list[dict[str, Any]]:
    """Normalize an index.json body into entries the UI can install from."""
    raw = payload.get("templates") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        return []
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry_id = str(item.get("id") or "").strip().lower()
        file_name = str(item.get("file") or f"templates/{entry_id}.toml").strip()
        if not entry_id or not file_name:
            continue
        entries.append(
            {
                "id": entry_id,
                "name": str(item.get("name") or entry_id),
                "vendor": str(item.get("vendor") or ""),
                "author": str(item.get("author") or ""),
                "description": str(item.get("description") or ""),
                "url": urllib.parse.urljoin(config.COMMUNITY_CATALOG_URL, file_name),
            }
        )
    return entries


def community_catalog() -> dict[str, Any]:
    """Cached community index. Never touches the network unless opted in."""
    if not config.COMMUNITY_CATALOG_CHECK:
        return {"enabled": False, "entries": [], "error": None, "url": config.COMMUNITY_CATALOG_URL}
    now = time.time()
    if now - float(_catalog_cache.get("checked_at") or 0) > config.COMMUNITY_CATALOG_CACHE_SECONDS:
        try:
            request = urllib.request.Request(
                config.COMMUNITY_CATALOG_URL,
                headers={"Accept": "application/json", "User-Agent": "Screenloop template catalog"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - operator-configured URL
                body = response.read(MAX_CATALOG_BYTES + 1)
            if len(body) > MAX_CATALOG_BYTES:
                raise ValueError("catalog index is too large")
            _catalog_cache.update(
                {
                    "checked_at": now,
                    "entries": parse_catalog(json.loads(body.decode("utf-8"))),
                    "error": None,
                }
            )
        except Exception as exc:
            # Cache the failure too, otherwise an unreachable catalog turns every
            # page load into a fresh outbound request.
            _catalog_cache.update({"checked_at": now, "entries": [], "error": str(exc)})
    return {
        "enabled": True,
        "entries": _catalog_cache.get("entries") or [],
        "error": _catalog_cache.get("error"),
        "url": config.COMMUNITY_CATALOG_URL,
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


SECURITY_EVENT_PREFIXES = ("login", "security", "user", "logout")


def visible_events(events: list[dict[str, Any]], user: dict[str, Any] | None) -> list[dict[str, Any]]:
    # `user is None` means an internal caller, not an anonymous one.
    if user is None:
        return events
    # Security audit entries (logins, denials, user changes) need their own
    # permission.
    if not has_permission(user, "event.security.view"):
        events = [e for e in events if not str(e.get("event_type") or "").startswith(SECURITY_EVENT_PREFIXES)]
    # An event naming a screen would otherwise disclose screens outside the
    # caller's scope -- their names, addresses and what is playing on them.
    scopes = scopes_for(user)
    if scopes.covers("tv.view"):
        return events
    allowed = {int(tv["id"]) for tv in visible_tvs(user, store.list_tvs())}
    return [e for e in events if e.get("tv_id") is None or int(e["tv_id"]) in allowed]


def public_tv(tv: dict[str, Any]) -> dict[str, Any]:
    """Remove controller-only resolver context from an API TV payload."""
    result = dict(tv)
    result.pop("schedule_groups", None)
    return result


def tvs_with_schedule(user: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """list_tvs plus why a screen is dark, resolved once for the whole list.

    The panel has to be able to say "outside its operating window" or
    "switched off at the screen" -- otherwise a TV that is deliberately not
    being pushed to looks identical to one that is broken.
    """
    settings = store.get_playback_schedule()
    moment = schedule.now()
    tvs = visible_tvs(user, store.list_tvs())
    for tv in tvs:
        window = schedule.resolve_window(tv, settings)
        tv["schedule_open"] = window.is_open(moment) if window else True
        tv["schedule_next_open_at"] = next_open_iso(window, moment)
        tv["playback_suspended"] = tv.get("playback_suspended_at") is not None
    return [public_tv(tv) for tv in tvs]


def live_snapshot(user: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "server_time": int(time.time()),
        "status": {
            "tvs": tvs_with_schedule(user),
            "media": visible_library(user, store.list_media(), "media.view"),
            "playlists": visible_library(user, store.list_playlists(), "playlist.view"),
            "transcode_jobs": visible_transcode_jobs(user),
        },
        "events": visible_events(store.list_events(limit=80), user),
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
    if not failures:
        bucket.pop(key, None)
        return False
    return len(failures) >= limit


def record_failure(bucket: dict[str, deque[float]], key: str) -> None:
    bucket[key].append(time.time())
    if len(bucket) > 4096:
        cutoff = time.time() - 3600
        for stale_key in [k for k, v in bucket.items() if not v or v[-1] < cutoff]:
            bucket.pop(stale_key, None)


def require_api_auth(request: Request) -> dict[str, Any]:
    token = request.cookies.get("screenloop_session")
    user = store.get_session_user(token)
    if not user:
        raise HTTPException(401, "Authentication required")
    request.state.user = user
    return user


def require_permission(*required: str):
    """Gate a route on permissions the caller must hold, all of them.

    Every key is checked against the catalogue at import time, so a typo in a
    gate is a startup failure rather than an endpoint that silently lets
    everybody through -- `permissions.KEYS` would simply never contain the
    misspelling, and `has_permission` would deny for all users including
    admins.
    """
    unknown = sorted(set(required) - permissions.KEYS)
    if unknown:
        raise RuntimeError(f"Unknown permission in route gate: {', '.join(unknown)}")

    global_only = sorted(set(required) & permissions.GLOBAL_ONLY)

    def dependency(request: Request, user: dict[str, Any] = Depends(require_api_auth)) -> dict[str, Any]:
        # Operations over the whole installation demand a grant over the whole
        # installation. The flat permission set cannot tell a company-wide
        # grant from one over a single branch, so without this a branch
        # operator satisfied these gates.
        if global_only and not all(scopes_for(user).holds_globally(key) for key in global_only):
            store.add_event(
                None,
                "security_denied",
                f"Denied {request.method} {request.url.path}: needs a global grant",
                f"{user['username']}; {', '.join(global_only)}",
            )
            raise HTTPException(403, "This action needs a permission granted across the whole installation")
        if not has_permission(user, *required):
            store.add_event(
                None,
                "security_denied",
                f"Denied {request.method} {request.url.path}",
                f"{user['username']}; missing {','.join(sorted(set(required) - granted_permissions(user)))}",
            )
            raise HTTPException(403, "Insufficient permissions")
        return user

    return dependency


def require_any_permission(*accepted: str):
    """Gate a route on holding **any one** of several permissions.

    For reads that a stronger permission obviously implies. `role.view` exists
    so an auditor can read the roles table without being able to change it, but
    a `role.manage` holder reads it too, and splitting the read out must not
    take away access somebody already had -- including a branch administrator,
    whose `role.manage` is deliberately scoped.

    A global-only key still needs a global grant to count; it just is not the
    only way through the door.
    """
    unknown = sorted(set(accepted) - permissions.KEYS)
    if unknown:
        raise RuntimeError(f"Unknown permission in route gate: {', '.join(unknown)}")

    def dependency(request: Request, user: dict[str, Any] = Depends(require_api_auth)) -> dict[str, Any]:
        granted = granted_permissions(user)
        for key in accepted:
            if key not in granted:
                continue
            if key in permissions.GLOBAL_ONLY and not scopes_for(user).holds_globally(key):
                continue
            return user
        store.add_event(
            None,
            "security_denied",
            f"Denied {request.method} {request.url.path}",
            f"{user['username']}; missing {','.join(sorted(accepted))}",
        )
        raise HTTPException(403, "Insufficient permissions")

    return dependency


def scopes_for(user: dict[str, Any] | None) -> permissions.Scopes:
    """The caller's grants resolved against the group tree, once per request."""
    if not user:
        return permissions.Scopes((), {})
    cached = user.get("_scopes")
    if isinstance(cached, permissions.Scopes):
        return cached
    resolved = permissions.Scopes(store.user_grants(int(user["id"])), store.group_parents())
    user["_scopes"] = resolved
    return resolved


def ensure_covers(user: dict[str, Any], permission: str, *, group_id: int | None = None, node_id: int | None = None):
    """403 unless the caller holds `permission` over this particular object."""
    if scopes_for(user).covers(permission, group_id=group_id, node_id=node_id):
        return
    store.add_event(
        None,
        "security_denied",
        f"Denied {permission} outside granted scope",
        f"{user['username']}; group={group_id}; node={node_id}",
    )
    raise HTTPException(403, "Insufficient permissions for this object")


def ensure_covers_tv(user: dict[str, Any], permission: str, tv: dict[str, Any]) -> None:
    ensure_covers(user, permission, group_id=tv.get("group_id"), node_id=tv.get("node_id"))


def visible_groups(user: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Groups the caller may see, plus the ancestors needed to render the tree.

    A grant on "МФЦ Воронеж / 2-й этаж" has to leave the parent visible, or the
    branch appears at the root with no context and the indentation lies.
    """
    scopes = scopes_for(user)
    groups = store.list_groups()
    if scopes.covers("group.view"):
        return groups
    keep: set[int] = set()
    for group in groups:
        if scopes.covers("group.view", group_id=int(group["id"])):
            keep |= scopes.ancestors(int(group["id"]))
    return [group for group in groups if int(group["id"]) in keep]


def visible_tvs(user: dict[str, Any] | None, tvs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Screens the caller may see. Without this the dashboard leaks everything."""
    scopes = scopes_for(user)
    if scopes.covers("tv.view"):
        return tvs
    return [tv for tv in tvs if scopes.covers_tv("tv.view", tv)]


def visible_library(user: dict[str, Any] | None, rows: list[dict[str, Any]], permission: str) -> list[dict[str, Any]]:
    """Clips or playlists the caller may see.

    A row with no group is shared: anyone holding the permission anywhere sees
    it, because a branch has to be able to put a corporate clip into its own
    playlist. Everything else has to be covered by the caller's scopes.
    """
    scopes = scopes_for(user)
    if scopes.covers(permission):
        return rows
    return [row for row in rows if row.get("group_id") is None or scopes.covers(permission, group_id=row["group_id"])]


def ensure_may_see_library_row(user: dict[str, Any], permission: str, row: dict[str, Any]) -> None:
    """404-equivalent for a single clip or playlist outside the caller's reach."""
    if row.get("group_id") is None or scopes_for(user).covers(permission, group_id=row["group_id"]):
        return
    raise HTTPException(403, "Insufficient permissions for this object")


def visible_transcode_jobs(user: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Jobs follow the visibility of the clip they belong to."""
    scopes = scopes_for(user)
    if scopes.covers("transcode.view"):
        return store.list_transcode_jobs()
    groups = {int(m["id"]): m.get("group_id") for m in store.list_media()}
    return [
        job
        for job in store.list_transcode_jobs()
        if groups.get(int(job["media_id"])) is None
        or scopes.covers("transcode.view", group_id=groups[int(job["media_id"])])
    ]


def ensure_may_edit_shared(user: dict[str, Any], permission: str, row: dict[str, Any]) -> None:
    """Changing something shared with the whole company needs company-wide say.

    Seeing a shared clip is not the same as owning it; otherwise any branch
    could rename or delete the corporate library.
    """
    if row.get("group_id") is not None:
        ensure_covers(user, permission, group_id=row["group_id"])
        return
    if scopes_for(user).holds_globally(permission):
        return
    store.add_event(
        None,
        "security_denied",
        f"Denied {permission} on a shared item",
        f"{user['username']}; needs a global grant",
    )
    raise HTTPException(403, "Shared items can only be changed with a permission granted across the installation")


def granted_permissions(user: dict[str, Any] | None) -> frozenset[str]:
    if not user:
        return frozenset()
    return permissions.normalise(user.get("permissions") or ())


def has_permission(user: dict[str, Any] | None, *required: str) -> bool:
    return bool(required) and set(required) <= granted_permissions(user)


# Permissions compose, so the old assumption that only an all-powerful admin
# could reach these endpoints no longer holds. Two invariants keep a holder of
# role.manage or user.manage from becoming an admin, or from locking everybody
# out.
ADMINISTRATIVE_PERMISSIONS = ("role.manage", "user.manage")


def ensure_may_grant(actor: dict[str, Any], wanted: frozenset[str]) -> None:
    """Refuse to hand out authority the caller does not hold.

    Without this, a custom role carrying role.manage could mint a role with
    every permission and assign it to itself, and one carrying user.manage
    could simply create an admin.
    """
    excess = sorted(wanted - granted_permissions(actor))
    if excess:
        raise HTTPException(403, f"You cannot grant permissions you do not hold: {', '.join(excess)}")


def ensure_authority_survives(role_id: int, remaining: frozenset[str]) -> None:
    """Refuse a role change that would leave nobody able to administer.

    Checked before the write rather than after, so there is nothing to undo.
    """
    for permission in ADMINISTRATIVE_PERMISSIONS:
        if permission in remaining:
            continue
        if store.users_with_permission_excluding_role(permission, role_id):
            continue
        raise HTTPException(400, f"This would leave nobody holding {permission}")


def role_or_404(role_id: int) -> dict[str, Any]:
    role = store.get_role(role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    return role


def ensure_role_is_editable(role: dict[str, Any]) -> None:
    if role.get("builtin"):
        raise HTTPException(400, "Built-in roles cannot be changed or removed")


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


def ensure_allowed_control_url(control_url: str | None) -> None:
    url = (control_url or "").strip()
    if not url:
        return
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise HTTPException(400, "control_url must be a plain http:// URL")
    if not config.ALLOWED_TV_CIDRS:
        return
    try:
        addr = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise HTTPException(400, "control_url must point at a TV IP address") from exc
    if not any(addr in ipaddress.ip_network(cidr, strict=False) for cidr in config.ALLOWED_TV_CIDRS):
        raise HTTPException(403, "control_url is outside allowed TV networks")


def ensure_command_rate(request: Request, tv_id: int) -> None:
    key = f"command:{client_ip(request)}:{tv_id}"
    if rate_limited(_action_failures, key, 30, 60):
        raise HTTPException(429, "Too many TV commands")
    record_failure(_action_failures, key)


def global_permissions(user: dict[str, Any]) -> set[str]:
    """The subset held over the whole installation.

    The panel needs it to know that a shared clip is out of reach: without it
    the branch would be shown edit buttons that can only ever answer 403.
    """
    scopes = scopes_for(user)
    return {key for key in granted_permissions(user) if scopes.holds_globally(key)}


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "disabled": bool(user.get("disabled", 0)),
        "permissions": sorted(granted_permissions(user)),
    }


def require_password_strength(password: str) -> None:
    if len(password) < config.MIN_PASSWORD_LENGTH and not config.ALLOW_INSECURE_AUTH:
        raise HTTPException(400, f"Password must contain at least {config.MIN_PASSWORD_LENGTH} characters")


def tv_or_404(tv_id: int) -> dict[str, Any]:
    tv = store.get_tv(tv_id)
    if not tv:
        raise HTTPException(404, "TV not found")
    return tv


def group_or_404(group_id: int) -> dict[str, Any]:
    group = store.get_group(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    return group


def playlist_or_404(playlist_id: int) -> dict[str, Any]:
    playlist = store.get_playlist(playlist_id)
    if not playlist:
        raise HTTPException(404, "Playlist not found")
    return playlist


def profiles_in_use() -> list[str]:
    """Profiles worth transcoding for right now: those assigned to a TV, plus the fallback.

    Transcoding every uploaded file into every installed profile would scale with
    the number of community templates an operator happens to have installed.
    Worker.is_item_playable queues the job lazily when a TV switches profile.
    """
    used = {profile_or_default(profile) for profile in store.distinct_tv_profiles()}
    used.add(DEFAULT_PROFILE)
    return sorted(used)


def resolve_upload_group(user: dict[str, Any], requested: int | None) -> int | None:
    """Where an uploaded clip lands.

    An upload has to land inside the zone the uploader was granted, or the
    scoping the rest of the library obeys would be undone at the front door:
    every branch upload would arrive in the shared corporate library. A branch
    cannot upload straight into that library at all -- publishing is the
    separate, separately guarded step in `api_set_media_owner`.
    """
    scopes = scopes_for(user)
    if requested is not None:
        group_or_404(requested)
        ensure_covers(user, "media.upload", group_id=requested)
        return requested
    if scopes.holds_globally("media.upload"):
        return None
    granted = {gid for gid in scopes.scopes_for("media.upload").get(permissions.GROUP, set()) if gid is not None}
    if len(granted) == 1:
        return int(next(iter(granted)))
    # Several branches, or a node-only grant: the uploader has to say which one,
    # because guessing would silently file the clip under the wrong department.
    raise HTTPException(400, "Choose the group this upload belongs to")


def save_upload(file: UploadFile, user: dict[str, Any], group_id: int | None) -> int:
    original_name = Path(file.filename or "upload.bin").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(400, f"Unsupported video extension: {suffix}")

    try:
        free_bytes = shutil.disk_usage(config.MEDIA_DIR).free
    except OSError:
        free_bytes = None
    if free_bytes is not None and free_bytes < config.MIN_FREE_DISK_BYTES:
        raise HTTPException(507, "Not enough free disk space for uploads")

    digest = hashlib.sha1(f"{original_name}:{secrets.token_hex(8)}".encode()).hexdigest()[:16]
    target = config.MEDIA_DIR / f"{Path(original_name).stem}.{digest}{suffix}"
    written = 0
    try:
        with target.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Uploaded file is too large")
                out.write(chunk)
    except HTTPException:
        unlink_quiet(target)
        raise
    except OSError as exc:
        unlink_quiet(target)
        raise HTTPException(507, "Failed to store uploaded file") from exc
    duration = probe_duration_seconds(target)
    if duration is None:
        unlink_quiet(target)
        store.add_event(None, "upload_rejected", f"Rejected unreadable video {original_name}", user["username"])
        raise HTTPException(400, "Uploaded file is not a readable video")

    # New clips inherit the site defaults, so an operator who wants every
    # upload muted sets it once instead of per file.
    defaults = store.get_media_defaults()
    media_id = store.add_media(
        Path(original_name).stem,
        target,
        original_name,
        target.stat().st_size,
        media_digest(target),
        duration,
        silent=defaults["silent"],
        compressed=defaults["compressed"],
    )
    if group_id is not None:
        store.set_media_group(media_id, group_id)
    # An upload is a draft until somebody with media.approve publishes it. The
    # transcodes still run, so approving is one click and not a wait.
    store.set_media_lifecycle(media_id, lifecycle.ON_UPLOAD)
    for profile in profiles_in_use():
        store.ensure_transcode_job(media_id, profile)
    # The audit line has to answer "what exactly arrived" on its own: an
    # incident review reads events, not the media table as it stands today.
    store.add_event(
        None,
        "media_uploaded",
        f"Uploaded {original_name} ({written} bytes) into {'shared library' if group_id is None else f'group {group_id}'}",
        user["username"],
    )
    return media_id


def startup() -> None:
    config.validate_security_config()
    for problem in reload_profiles():
        logger.warning("Ignoring TV template: %s", problem)
    if store.user_count() == 0:
        config.validate_bootstrap_password()
    created = store.ensure_bootstrap_admin(config.BOOTSTRAP_USER, config.BOOTSTRAP_PASSWORD)
    if created:
        store.add_event(None, "security_bootstrap", f"Created bootstrap admin {config.BOOTSTRAP_USER}")
    store.cleanup_sessions()
    store.fail_running_commands()
    store.mark_all_nodes_offline()
    worker.start()


def shutdown() -> None:
    worker.stop()


@app.post("/api/v1/auth/login", tags=["auth"], summary="Create a web/API session")
def api_login(request: Request, payload: LoginRequest):
    ip = client_ip(request)
    username_key = f"user:{payload.username.strip().lower()}"
    if rate_limited(_auth_failures, ip, 10, 300) or rate_limited(_auth_failures, username_key, 10, 300):
        store.add_event(None, "login_rate_limited", "API login rate limited", ip)
        raise HTTPException(429, "Too many login attempts")
    user = store.authenticate_user(payload.username, payload.password)
    if not user:
        record_failure(_auth_failures, ip)
        record_failure(_auth_failures, username_key)
        store.add_event(None, "login_failed", f"API login failed for {payload.username}", ip)
        raise HTTPException(401, "Invalid credentials")
    token = store.create_session(user["id"], ip, request.headers.get("user-agent", ""))
    store.add_event(None, "login_success", f"API login success for {user['username']}", ip)
    response = JSONResponse(
        {
            "user": public_user(user),
            "csrf_token": create_csrf_token(token),
            # Same shape as /api/v1/session: the panel decides what to render
            # from this and must not have to make a second call to find out.
            "permissions": sorted(granted_permissions(user)),
            "global_permissions": sorted(global_permissions(user)),
            "roles": store.user_roles(int(user["id"])),
        }
    )
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
@app.get("/profile", response_class=HTMLResponse, include_in_schema=False)
@app.get("/nodes", response_class=HTMLResponse, include_in_schema=False)
@app.get("/diagnostics", response_class=HTMLResponse, include_in_schema=False)
@app.get("/settings", response_class=HTMLResponse, include_in_schema=False)
@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
@app.get("/ui/{path:path}", response_class=HTMLResponse, include_in_schema=False)
def vue_ui(path: str = ""):
    index_path = FRONTEND_DIST / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "Vue UI is not built in this image")
    return FileResponse(index_path)


@app.post("/api/v1/me/password", tags=["auth"], summary="Change own password")
def api_change_own_password(
    request: Request,
    payload: SelfPasswordChangeRequest,
    user: dict[str, Any] = Depends(require_api_auth),
    _: None = Depends(api_csrf_guard),
):
    ip = client_ip(request)
    change_key = f"pwchange:{ip}"
    if rate_limited(_action_failures, change_key, 10, 300):
        raise HTTPException(429, "Too many password change attempts")
    full_user = store.get_user_by_username(user["username"])
    if not full_user or not verify_password(payload.current_password, full_user.get("password_hash")):
        record_failure(_action_failures, change_key)
        store.add_event(None, "user_password_change_denied", f"Wrong current password for {user['username']}", ip)
        raise HTTPException(403, "Current password is incorrect")
    require_password_strength(payload.new_password)
    store.set_user_password(user["id"], payload.new_password, keep_token=request.cookies.get("screenloop_session"))
    store.add_event(None, "user_password_changed", f"{user['username']} changed own password", user["username"])
    return {"ok": True}


@app.get("/api/v1/me/sessions", tags=["auth"], summary="List own active sessions")
def api_my_sessions(request: Request, user: dict[str, Any] = Depends(require_api_auth)):
    return {"sessions": store.list_sessions_for_user(user["id"], request.cookies.get("screenloop_session"))}


@app.delete("/api/v1/me/sessions", tags=["auth"], summary="Log out everywhere except the current session")
def api_delete_other_sessions(
    request: Request,
    user: dict[str, Any] = Depends(require_api_auth),
    _: None = Depends(api_csrf_guard),
):
    removed = store.delete_other_sessions(user["id"], request.cookies.get("screenloop_session"))
    store.add_event(None, "user_sessions_revoked", f"{user['username']} revoked {removed} other sessions", user["username"])
    return {"removed": removed}


@app.delete("/api/v1/me/sessions/{session_id}", tags=["auth"], summary="Revoke one of your own sessions")
def api_delete_own_session(
    session_id: int,
    user: dict[str, Any] = Depends(require_api_auth),
    _: None = Depends(api_csrf_guard),
):
    if not store.delete_session_by_id(user["id"], session_id):
        raise HTTPException(404, "Session not found")
    store.add_event(None, "user_sessions_revoked", f"{user['username']} revoked session {session_id}", user["username"])
    return {"ok": True}


@app.get("/api/v1/session", tags=["auth"], summary="Get current user and CSRF token")
def api_session(request: Request, user: dict[str, Any] = Depends(require_api_auth)):
    return {
        "user": public_user(user),
        "csrf_token": create_csrf_token(request.cookies.get("screenloop_session", "")),
        "permissions": sorted(granted_permissions(user)),
        "global_permissions": sorted(global_permissions(user)),
        # What this person actually holds, and where. `user.role` next to it is
        # the legacy level, which says "viewer" about somebody who runs a branch.
        "roles": store.user_roles(int(user["id"])),
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
def api_v1_diagnostics(_: dict[str, Any] = Depends(require_permission("diagnostics.view"))):
    return diagnostics_snapshot()


@app.get("/api/v1/status", tags=["status"], summary="Get live dashboard state")
def api_v1_status(user: dict[str, Any] = Depends(require_api_auth)):
    return {
        "app": APP_NAME,
        "tvs": tvs_with_schedule(user),
        "media": visible_library(user, store.list_media(), "media.view"),
        "playlists": visible_library(user, store.list_playlists(), "playlist.view"),
        "transcode_jobs": visible_transcode_jobs(user),
    }


@app.get("/api/v1/media", tags=["media"], summary="List media")
def api_list_media(user: dict[str, Any] = Depends(require_permission("media.view"))):
    return {"media": visible_library(user, store.list_media(), "media.view")}


@app.post("/api/v1/media/upload", tags=["media"], summary="Upload media")
def api_upload_media(
    request: Request,
    file: UploadFile = File(...),
    group_id: str | None = Form(None),
    user: dict[str, Any] = Depends(require_permission("media.upload")),
    _: None = Depends(api_csrf_guard),
):
    # Rate limited per address and per account: one throttles a compromised
    # network position, the other a compromised account behind a proxy.
    for upload_key in (f"upload:{client_ip(request)}", f"upload-user:{user['id']}"):
        if rate_limited(_action_failures, upload_key, 20, 3600):
            raise HTTPException(429, "Too many uploads")
        record_failure(_action_failures, upload_key)
    requested = int(group_id) if group_id and group_id.isdigit() else None
    media_id = save_upload(file, user, resolve_upload_group(user, requested))
    return {"id": media_id, "media": store.get_media(media_id)}


@app.patch("/api/v1/media/{media_id}", tags=["media"], summary="Update a clip")
def api_update_media(
    media_id: int,
    payload: MediaUpdateRequest,
    user: dict[str, Any] = Depends(require_permission("media.manage")),
    _: None = Depends(api_csrf_guard),
):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    ensure_may_edit_shared(user, "media.manage", media)

    title = payload.title.strip()
    description = (payload.description or "").strip()
    if title != media["title"] or description != (media.get("description") or ""):
        store.update_media(media_id, title, description)
        store.add_event(None, "media_updated", f"API updated media {media_id} ({title})", user["username"])

    # Audio and size affect the prepared copies, so a change here has to send the
    # clip back through ffmpeg -- the same rule the single-purpose toggles follow.
    requeue = False
    if payload.silent is not None and bool(media.get("silent")) != payload.silent:
        store.set_media_silent(media_id, payload.silent)
        requeue = True
    if payload.compressed is not None and bool(media.get("compressed")) != payload.compressed:
        store.set_media_compressed(media_id, payload.compressed)
        requeue = True
    if requeue:
        store.requeue_transcode_jobs_for_media(media_id)

    # Omitted means "leave it", null means "never expires"; the two have to be
    # told apart or every rename would clear the deadline.
    if "expires_at" in payload.model_fields_set and payload.expires_at != lifecycle.expires_at(media):
        store.set_media_expiry(media_id, payload.expires_at)
        store.add_event(
            None,
            "media_expiry_set",
            f"API set expiry for media {media_id}",
            f"{user['username']}; expires_at={payload.expires_at}",
        )

    return {"ok": True, "media": store.get_media(media_id)}


@app.get("/api/v1/media/{media_id}/usage", tags=["media"], summary="Where a clip is used")
def api_media_usage(media_id: int, user: dict[str, Any] = Depends(require_permission("media.view"))):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    ensure_may_see_library_row(user, "media.view", media)
    usage = store.media_usage(media_id)
    # A branch must not learn about other branches through this list.
    return {
        "playlists": visible_library(user, usage["playlists"], "playlist.view"),
        "tvs": visible_tvs(user, usage["tvs"]),
    }


@app.get("/api/v1/media/{media_id}/poster", tags=["media"], summary="Still frame for a clip")
def api_media_poster(media_id: int, user: dict[str, Any] = Depends(require_permission("media.view"))):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    ensure_may_see_library_row(user, "media.view", media)
    poster = str(media.get("poster_path") or "")
    if not poster:
        raise HTTPException(404, "No poster frame for this clip")
    path = Path(poster)
    if not path.exists():
        # Somebody cleared the posters directory, or restored a database next
        # to an older volume. Forgetting the path puts the clip back in the
        # worker's queue, so the still comes back by itself instead of being
        # lost until the file is re-uploaded.
        store.set_media_poster(media_id, None)
        raise HTTPException(404, "Poster frame not found")
    # The name carries the file's digest, so a still never changes under a URL:
    # replacing the clip produces a different one. Private, because the picture
    # is as confidential as the clip it was taken from.
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.get("/api/v1/media/{media_id}/preview", tags=["media"], summary="Play a clip in the panel")
def api_media_preview(media_id: int, request: Request, user: dict[str, Any] = Depends(require_permission("media.view"))):
    """Deliberately not /stream: that route is for screens.

    It is signed against a TV's address, and fetching it tells the controller a
    TV started playing. Somebody watching a clip at their desk must not move a
    playlist along, so the panel gets its own route behind the session cookie
    and the same visibility rules as the library list.
    """
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    ensure_may_see_library_row(user, "media.view", media)
    path = preview_path(media_id)
    return ranged_file_response(path, request, send_body=True)


def preview_path(media_id: int) -> Path:
    """The transcoded file the panel plays: TV-safe MP4 a browser also accepts."""
    transcode_row = store.get_transcode(media_id, profile_or_default("generic_dlna"))
    if not transcode_row or transcode_row["status"] != "done" or not transcode_row["output_path"]:
        raise HTTPException(404, "Media is not ready")
    path = Path(transcode_row["output_path"])
    if not path.exists():
        raise HTTPException(404, "Transcoded file not found")
    return path


@app.post("/api/v1/media/{media_id}/silent", tags=["media"], summary="Toggle silent audio for media")
def api_set_media_silent(
    media_id: int,
    payload: MediaSilentRequest,
    user: dict[str, Any] = Depends(require_permission("media.manage")),
    _: None = Depends(api_csrf_guard),
):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    ensure_may_edit_shared(user, "media.manage", media)
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
    user: dict[str, Any] = Depends(require_permission("media.manage")),
    _: None = Depends(api_csrf_guard),
):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    ensure_may_edit_shared(user, "media.manage", media)
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


@app.post("/api/v1/media/{media_id}/publish", tags=["media"], summary="Publish a clip")
def api_publish_media(
    media_id: int,
    user: dict[str, Any] = Depends(require_permission("media.approve")),
    _: None = Depends(api_csrf_guard),
):
    """The approval gate: a branch uploads a draft, an approver publishes it."""
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    ensure_may_edit_shared(user, "media.approve", media)
    if lifecycle.state(media) != lifecycle.PUBLISHED:
        store.set_media_lifecycle(media_id, lifecycle.PUBLISHED)
        store.add_event(
            None,
            "media_published",
            f"API published media {media_id} ({media['title']})",
            f"{user['username']}; from {lifecycle.state(media)}",
        )
        push_all_node_configs()
    return {"ok": True, "media": store.get_media(media_id)}


@app.delete("/api/v1/media/{media_id}", tags=["media"], summary="Archive a clip")
def api_delete_media(media_id: int, user: dict[str, Any] = Depends(require_permission("media.delete")), _: None = Depends(api_csrf_guard)):
    """Deleting archives. It used to cascade the clip out of every playlist and
    unlink the files, which is how a screen lost the thing it was playing with
    no way back. Destroying is now `media.purge`, and only from here."""
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    ensure_may_edit_shared(user, "media.delete", media)
    if lifecycle.state(media) != lifecycle.ARCHIVED:
        store.set_media_lifecycle(media_id, lifecycle.ARCHIVED)
        store.add_event(None, "media_archived", f"API archived media {media_id}", user["username"])
        push_all_node_configs()
    return {"ok": True, "media": store.get_media(media_id)}


@app.post("/api/v1/media/{media_id}/purge", tags=["media"], summary="Destroy an archived clip")
def api_purge_media(
    media_id: int,
    user: dict[str, Any] = Depends(require_permission("media.purge")),
    _: None = Depends(api_csrf_guard),
):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    ensure_may_edit_shared(user, "media.purge", media)
    # Two refusals, both irreversible if skipped: archiving is the pause that
    # makes a purge deliberate, and a clip a playlist still holds is a clip a
    # screen may be about to ask for.
    if lifecycle.state(media) != lifecycle.ARCHIVED:
        raise HTTPException(409, "Only an archived clip can be permanently deleted")
    if store.media_is_referenced(media_id):
        raise HTTPException(409, "This clip is still used by a playlist")
    paths = [media["original_path"], *store.media_output_paths(media_id)]
    store.delete_media(media_id)
    for item in paths:
        unlink_quiet(Path(item))
    store.add_event(None, "media_purged", f"API permanently deleted media {media_id} ({media['title']})", user["username"])
    return {"ok": True}


@app.get("/api/v1/playlists", tags=["playlists"], summary="List playlists")
def api_list_playlists(user: dict[str, Any] = Depends(require_permission("playlist.view"))):
    return {"playlists": visible_library(user, store.list_playlists(), "playlist.view")}


@app.post("/api/v1/playlists", tags=["playlists"], summary="Create playlist")
def api_create_playlist(payload: PlaylistCreateRequest, user: dict[str, Any] = Depends(require_permission("playlist.edit")), _: None = Depends(api_csrf_guard)):
    playlist_id = store.create_playlist(payload.name.strip())
    store.add_event(None, "playlist_created", f"API created playlist {payload.name.strip()}", user["username"])
    return {"id": playlist_id, "playlist": store.get_playlist(playlist_id)}


@app.get("/api/v1/playlists/{playlist_id}", tags=["playlists"], summary="Get playlist with items")
def api_get_playlist(playlist_id: int, user: dict[str, Any] = Depends(require_permission("playlist.view"))):
    playlist = playlist_or_404(playlist_id)
    ensure_may_see_library_row(user, "playlist.view", playlist)
    return {"playlist": playlist, "items": store.playlist_items(playlist_id)}


@app.delete("/api/v1/playlists/{playlist_id}", tags=["playlists"], summary="Delete playlist")
def api_delete_playlist(playlist_id: int, user: dict[str, Any] = Depends(require_permission("playlist.delete")), _: None = Depends(api_csrf_guard)):
    playlist = playlist_or_404(playlist_id)
    ensure_may_edit_shared(user, "playlist.delete", playlist)
    store.delete_playlist(playlist_id)
    store.add_event(None, "playlist_deleted", f"API deleted playlist {playlist['name']}", user["username"])
    return {"ok": True}


@app.post("/api/v1/playlists/{playlist_id}/items", tags=["playlists"], summary="Add playlist item")
def api_add_playlist_item(
    playlist_id: int,
    payload: PlaylistItemRequest,
    user: dict[str, Any] = Depends(require_permission("playlist.edit")),
    _: None = Depends(api_csrf_guard),
):
    playlist_or_404(playlist_id)
    if not store.get_media(payload.media_id):
        raise HTTPException(404, "Media not found")
    store.add_playlist_item(playlist_id, payload.media_id)
    store.add_event(None, "playlist_item_added", f"API added media {payload.media_id} to playlist {playlist_id}", user["username"])
    push_all_node_configs()
    return {"ok": True, "items": store.playlist_items(playlist_id)}


@app.delete("/api/v1/playlist-items/{item_id}", tags=["playlists"], summary="Remove playlist item")
def api_delete_playlist_item(item_id: int, user: dict[str, Any] = Depends(require_permission("playlist.edit")), _: None = Depends(api_csrf_guard)):
    store.remove_playlist_item(item_id)
    store.add_event(None, "playlist_item_removed", f"API removed playlist item {item_id}", user["username"])
    push_all_node_configs()
    return {"ok": True}


@app.post("/api/v1/playlist-items/{item_id}/move", tags=["playlists"], summary="Move playlist item")
def api_move_playlist_item(
    item_id: int,
    payload: PlaylistMoveRequest,
    user: dict[str, Any] = Depends(require_permission("playlist.edit")),
    _: None = Depends(api_csrf_guard),
):
    store.move_playlist_item(item_id, payload.direction)
    store.add_event(None, "playlist_item_moved", f"API moved playlist item {item_id} {payload.direction}", user["username"])
    push_all_node_configs()
    return {"ok": True}


@app.post("/api/v1/playlist-items/{item_id}/position", tags=["playlists"], summary="Move playlist item to a position")
def api_set_playlist_item_position(
    item_id: int,
    payload: PlaylistPositionRequest,
    user: dict[str, Any] = Depends(require_permission("playlist.edit")),
    _: None = Depends(api_csrf_guard),
):
    store.set_playlist_item_position(item_id, payload.position)
    store.add_event(None, "playlist_item_moved", f"API moved playlist item {item_id} to {payload.position}", user["username"])
    return {"ok": True}


@app.get("/api/v1/tvs", tags=["tvs"], summary="List TVs and profiles")
def api_list_tvs(user: dict[str, Any] = Depends(require_permission("tv.view"))):
    return {"tvs": [public_tv(tv) for tv in visible_tvs(user, store.list_tvs())], "profiles": PROFILES}


@app.get("/api/v1/tvs/export", tags=["tvs"], summary="Export TV configs")
def api_export_tvs(_: dict[str, Any] = Depends(require_permission("tv.transfer"))):
    return {
        "version": 1,
        "app": APP_NAME,
        "exported_at": int(time.time()),
        "tvs": store.export_tvs(),
    }


@app.post("/api/v1/tvs/import", tags=["tvs"], summary="Import TV configs")
def api_import_tvs(payload: dict[str, Any], user: dict[str, Any] = Depends(require_permission("tv.transfer")), _: None = Depends(api_csrf_guard)):
    tvs = payload.get("tvs") if isinstance(payload, dict) else None
    if not isinstance(tvs, list):
        raise HTTPException(400, "Import must contain a tvs list")
    for item in tvs:
        if isinstance(item, dict) and item.get("ip"):
            ensure_allowed_tv_ip(str(item["ip"]).strip())
        if isinstance(item, dict):
            ensure_allowed_control_url(str(item.get("control_url") or ""))
    created, updated = store.import_tvs(tvs)
    store.add_event(None, "tv_import", f"API imported TV configs: {created} created, {updated} updated", user["username"])
    return {"created": created, "updated": updated}


@app.get("/api/v1/tvs/scan", tags=["tvs"], summary="Scan network for TVs")
def api_scan_tvs(_: dict[str, Any] = Depends(require_permission("tv.scan"))):
    from .dlna import discover_renderers_multi, get_local_ip_for

    existing = {tv["ip"]: tv for tv in store.list_tvs()}
    bind_ips = list(dict.fromkeys([*config.ADVERTISE_HOSTS, get_local_ip_for(next(iter(existing.keys()), "239.255.255.250"))]))
    found = discover_renderers_multi(bind_ips)
    for item in found:
        item["profile"] = detect_profile(item.get("manufacturer"), item.get("model_name"), item.get("friendly_name"))
        item["configured"] = item.get("ip") in existing
    return {"devices": found, "profiles": PROFILES, "bind_ips": bind_ips}


@app.post("/api/v1/tvs", tags=["tvs"], summary="Create TV")
def api_create_tv(payload: TvCreateRequest, user: dict[str, Any] = Depends(require_permission("tv.manage")), _: None = Depends(api_csrf_guard)):
    ensure_covers(user, "tv.manage", group_id=payload.group_id, node_id=payload.node_id)
    ip = payload.ip.strip()
    if payload.node_id is not None and not store.get_node(payload.node_id):
        raise HTTPException(404, "Node not found")
    if payload.node_id is None:
        # Node TVs live in a remote LAN; the local allowlist does not apply there.
        ensure_allowed_tv_ip(ip)
    allow_stream_for_ip(ip)
    if payload.group_id is not None:
        group_or_404(payload.group_id)
    tv_id = store.add_tv(payload.name.strip() or ip, ip, profile_or_default(payload.profile))
    if payload.group_id is not None:
        store.set_tv_group(tv_id, payload.group_id)
    if payload.node_id is not None:
        store.set_tv_node(tv_id, payload.node_id)
        push_node_config(payload.node_id)
    store.add_event(tv_id, "tv_added", f"API added TV {ip}", user["username"])
    return {"id": tv_id, "tv": public_tv(tv_or_404(tv_id))}


@app.patch("/api/v1/tvs/{tv_id}", tags=["tvs"], summary="Update TV")
def api_update_tv(
    tv_id: int,
    payload: TvUpdateRequest,
    user: dict[str, Any] = Depends(require_permission("tv.manage")),
    _: None = Depends(api_csrf_guard),
):
    previous_tv = tv_or_404(tv_id)
    ensure_covers_tv(user, "tv.manage", previous_tv)
    if payload.schedule_mode != (previous_tv.get("schedule_mode") or schedule.INHERIT):
        ensure_covers_tv(user, "schedule.manage", previous_tv)
    # Putting a playlist on a screen is a daily operation; it should not require
    # the authority to rename the screen, change its address or delete it.
    if payload.playlist_id != previous_tv.get("active_playlist_id"):
        ensure_covers_tv(user, "playlist.assign", previous_tv)
        if payload.playlist_id is not None:
            ensure_may_see_library_row(user, "playlist.view", playlist_or_404(payload.playlist_id))
    # A move crosses zones, so it is its own permission and it is checked at
    # both ends: over the branch the screen is leaving, or a branch
    # administrator could give away somebody else's screen, and over the one it
    # is entering, or they could push their screens into somebody else's tree.
    # tv.manage alone -- rename, address, profile, delete -- never moves a screen.
    moves_group = payload.group_id != previous_tv.get("group_id")
    moves_node = payload.node_id != previous_tv.get("node_id")
    if moves_group or moves_node:
        ensure_covers_tv(user, "tv.move", previous_tv)
    if moves_group:
        ensure_covers(user, "tv.move", group_id=payload.group_id)
    if moves_node and payload.node_id is not None:
        ensure_covers(user, "tv.move", node_id=payload.node_id)
    ip = payload.ip.strip()
    if payload.node_id is not None and not store.get_node(payload.node_id):
        raise HTTPException(404, "Node not found")
    if payload.node_id is None:
        # Node TVs live in a remote LAN; the local allowlist does not apply there.
        ensure_allowed_tv_ip(ip)
        ensure_allowed_control_url(payload.control_url)
    if previous_tv.get("ip") != ip:
        revoke_stream_for_ip(previous_tv.get("ip"))
    allow_stream_for_ip(ip)
    if payload.playlist_id is not None:
        playlist_or_404(payload.playlist_id)
    if payload.group_id is not None:
        group_or_404(payload.group_id)
    store.update_tv_config(
        tv_id,
        payload.name.strip(),
        ip,
        profile_or_default(payload.profile),
        payload.playlist_id,
        payload.autoplay,
        (payload.control_url or "").strip(),
    )
    apply_tv_schedule(tv_id, payload)
    if previous_tv.get("node_id") != payload.node_id:
        store.set_tv_node(tv_id, payload.node_id)
    if previous_tv.get("group_id") != payload.group_id:
        store.set_tv_group(tv_id, payload.group_id)
    store.add_event(tv_id, "tv_config_changed", f"API changed TV config {payload.name.strip()}", user["username"])
    for node_id in {previous_tv.get("node_id"), payload.node_id}:
        if node_id:
            push_node_config(int(node_id))
    return {"ok": True, "tv": public_tv(tv_or_404(tv_id))}


def normalize_schedule(
    mode: str | None,
    days: str | None,
    start: str | None,
    end: str | None,
) -> tuple[str, str | None, str | None, str | None]:
    """Validate and canonicalise the schedule tuple shared by TVs and groups."""
    mode = (mode or schedule.INHERIT).strip()
    if mode not in schedule.MODES:
        raise HTTPException(400, f"schedule_mode must be one of {', '.join(schedule.MODES)}")
    if mode != schedule.CUSTOM:
        return mode, None, None, None
    try:
        window = schedule.build_window(days, start or "", end or "")
    except schedule.ScheduleError as exc:
        raise HTTPException(400, str(exc)) from exc
    return (
        mode,
        schedule.format_days(window.days),
        schedule.format_time(window.start),
        schedule.format_time(window.end),
    )


def apply_owner(user: dict[str, Any], row: dict[str, Any], share_permission: str, group_id: int | None) -> None:
    """Move a clip or playlist between a branch and the shared library.

    Publishing is its own permission: a branch that may edit its own clips must
    not be able to make one company-wide, and taking something out of the
    shared library is the same act in reverse.
    """
    current = row.get("group_id")
    if current == group_id:
        return
    if current is None or group_id is None:
        ensure_covers(user, share_permission, group_id=current if group_id is None else group_id)
    if group_id is not None:
        if not store.get_group(group_id):
            raise HTTPException(404, "Group not found")
        ensure_covers(user, share_permission, group_id=group_id)


@app.put("/api/v1/media/{media_id}/owner", tags=["media"], summary="Move a clip between a group and the shared library")
def api_set_media_owner(
    media_id: int,
    payload: OwnerRequest,
    user: dict[str, Any] = Depends(require_permission("media.share")),
    _: None = Depends(api_csrf_guard),
):
    media = store.get_media(media_id)
    if not media:
        raise HTTPException(404, "Media not found")
    apply_owner(user, media, "media.share", payload.group_id)
    store.set_media_group(media_id, payload.group_id)
    store.add_event(None, "media_owner_changed", f"Media {media_id} moved to group {payload.group_id}", user["username"])
    return {"ok": True, "media": store.get_media(media_id)}


@app.put("/api/v1/playlists/{playlist_id}/owner", tags=["playlists"], summary="Move a playlist between a group and the shared library")
def api_set_playlist_owner(
    playlist_id: int,
    payload: OwnerRequest,
    user: dict[str, Any] = Depends(require_permission("playlist.share")),
    _: None = Depends(api_csrf_guard),
):
    playlist = playlist_or_404(playlist_id)
    apply_owner(user, playlist, "playlist.share", payload.group_id)
    store.set_playlist_group(playlist_id, payload.group_id)
    store.add_event(None, "playlist_owner_changed", f"Playlist {playlist_id} moved to group {payload.group_id}", user["username"])
    return {"ok": True, "playlist": store.get_playlist(playlist_id)}


@app.get("/api/v1/settings/media", tags=["media"], summary="Read the defaults applied to new uploads")
def api_get_media_defaults(_: dict[str, Any] = Depends(require_permission("media.view"))):
    return {"defaults": store.get_media_defaults()}


@app.put("/api/v1/settings/media", tags=["media"], summary="Set the defaults applied to new uploads")
def api_set_media_defaults(
    payload: MediaDefaultsRequest,
    user: dict[str, Any] = Depends(require_permission("media.defaults.manage")),
    _: None = Depends(api_csrf_guard),
):
    store.set_media_defaults(payload.silent, payload.compressed)
    store.add_event(
        None,
        "media_defaults_changed",
        f"Upload defaults: silent={payload.silent}, compressed={payload.compressed}",
        user["username"],
    )
    return {"ok": True, "defaults": store.get_media_defaults()}
def apply_tv_schedule(tv_id: int, payload: TvUpdateRequest) -> None:
    """Validate and store one TV's operating hours."""
    store.update_tv_schedule(
        tv_id,
        *normalize_schedule(
            payload.schedule_mode,
            payload.schedule_days,
            payload.schedule_start,
            payload.schedule_end,
        ),
    )


@app.get("/api/v1/schedule", tags=["schedule"], summary="Read the site-wide operating window")
def api_get_schedule(_: dict[str, Any] = Depends(require_permission("schedule.view"))):
    settings = store.get_playback_schedule()
    window = schedule.global_window(settings)
    moment = schedule.now()
    return {
        "schedule": settings,
        "timezone": str(moment.tzinfo),
        "now": moment.isoformat(),
        "open": window.is_open(moment) if window else True,
        "next_open_at": next_open_iso(window, moment),
    }


@app.put("/api/v1/schedule", tags=["schedule"], summary="Set the site-wide operating window")
def api_set_schedule(
    payload: ScheduleRequest,
    user: dict[str, Any] = Depends(require_permission("schedule.site.manage")),
    _: None = Depends(api_csrf_guard),
):
    try:
        window = schedule.build_window(payload.days, payload.start, payload.end)
    except schedule.ScheduleError as exc:
        raise HTTPException(400, str(exc)) from exc
    store.set_playback_schedule(
        payload.enabled,
        schedule.format_days(window.days),
        schedule.format_time(window.start),
        schedule.format_time(window.end),
    )
    state = "enabled" if payload.enabled else "disabled"
    store.add_event(
        None,
        "schedule_changed",
        f"Operating window {state}: {schedule.format_time(window.start)}-{schedule.format_time(window.end)}",
        user["username"],
    )
    push_all_node_configs()
    return {"ok": True, "schedule": store.get_playback_schedule()}


@app.post("/api/v1/tvs/{tv_id}/resume", tags=["tvs"], summary="Clear a playback suspension")
def api_resume_tv(
    tv_id: int,
    user: dict[str, Any] = Depends(require_permission("tv.command")),
    _: None = Depends(api_csrf_guard),
):
    ensure_covers_tv(user, "tv.command", tv_or_404(tv_id))
    resumed = store.resume_tv_playback(tv_id)
    if resumed:
        store.add_event(tv_id, "playback_resumed", "Playback suspension cleared", user["username"])
    return {"ok": True, "resumed": resumed, "tv": public_tv(tv_or_404(tv_id))}


def next_open_iso(window: schedule.Window | None, moment) -> str | None:
    if window is None:
        return None
    opens_at = window.next_open_at(moment)
    return opens_at.isoformat() if opens_at else None


@app.delete("/api/v1/tvs/{tv_id}", tags=["tvs"], summary="Delete TV")
def api_delete_tv(tv_id: int, user: dict[str, Any] = Depends(require_permission("tv.manage")), _: None = Depends(api_csrf_guard)):
    tv = tv_or_404(tv_id)
    ensure_covers_tv(user, "tv.manage", tv)
    stop_tv_before_delete(tv, user["username"], "api")
    store.delete_tv(tv_id)
    store.add_event(None, "tv_deleted", f"API deleted TV {tv['name']} / {tv['ip']}", user["username"])
    return {"ok": True}


@app.post("/api/v1/tvs/{tv_id}/detect", tags=["tvs"], summary="Detect TV metadata and control URL")
def api_detect_tv(
    request: Request,
    tv_id: int,
    user: dict[str, Any] = Depends(require_permission("tv.manage")),
    _: None = Depends(api_csrf_guard),
):
    from .dlna import discover_device, get_local_ip_for

    tv = tv_or_404(tv_id)
    ensure_covers_tv(user, "tv.manage", tv)
    if tv.get("node_id"):
        # The TV lives on a remote node's LAN; discovery must run there, not on the controller.
        ensure_command_rate(request, tv_id)
        command_id = store.enqueue_command(tv_id, "rediscover")
        store.add_event(tv_id, "manual_rediscover", "API queued rediscover", user["username"])
        return {"ok": True, "queued": True, "command_id": command_id}
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
    return {"ok": True, "tv": public_tv(tv_or_404(tv_id))}


@app.post("/api/v1/tvs/{tv_id}/commands", tags=["tvs"], summary="Queue TV playback command")
def api_tv_command(
    request: Request,
    tv_id: int,
    payload: TvCommandRequest,
    user: dict[str, Any] = Depends(require_permission("tv.command")),
    _: None = Depends(api_csrf_guard),
):
    tv = tv_or_404(tv_id)
    ensure_covers_tv(user, "tv.command", tv)
    # Rediscovery re-runs SSDP against the TV's network, so it needs the
    # device-management permission rather than plain playback control.
    if payload.command == "rediscover":
        ensure_covers_tv(user, "tv.manage", tv)
    ensure_command_rate(request, tv_id)
    # Marked manual so the worker lets it through the operating window and
    # clears a suspension: whoever pressed this can see the screen.
    command_id = store.enqueue_command(tv_id, payload.command, '{"manual": true}')
    store.add_event(tv_id, f"manual_{payload.command}", f"API queued {payload.command}", user["username"])
    return {"ok": True, "command_id": command_id}


@app.get("/api/v1/transcode/jobs", tags=["transcode"], summary="List transcode jobs")
def api_transcode_jobs(user: dict[str, Any] = Depends(require_permission("transcode.view"))):
    return {"jobs": visible_transcode_jobs(user)}


@app.post("/api/v1/transcode/jobs/{job_id}/rebuild", tags=["transcode"], summary="Rebuild transcode job")
def api_rebuild_transcode(job_id: int, user: dict[str, Any] = Depends(require_permission("transcode.rebuild")), _: None = Depends(api_csrf_guard)):
    store.rebuild_transcode_job(job_id)
    store.add_event(None, "transcode_rebuild", f"API rebuild queued for job {job_id}", user["username"])
    return {"ok": True}


@app.post("/api/v1/transcode/cleanup", tags=["transcode"], summary="Clean stale transcode cache")
def api_cleanup_transcode(user: dict[str, Any] = Depends(require_permission("transcode.manage")), _: None = Depends(api_csrf_guard)):
    referenced = {Path(path) for path in store.referenced_transcode_paths()}
    removed = 0
    for path in config.TRANSCODE_DIR.glob("*"):
        if path.is_file() and path not in referenced:
            unlink_quiet(path)
            removed += 1
    store.add_event(None, "cache_cleanup", f"API removed {removed} stale transcode files", user["username"])
    return {"removed": removed}


@app.get("/api/v1/groups", tags=["groups"], summary="List the TV group tree")
def api_list_groups(user: dict[str, Any] = Depends(require_permission("group.view"))):
    return {"groups": visible_groups(user), "max_depth": store.MAX_GROUP_DEPTH}


@app.post("/api/v1/groups", tags=["groups"], summary="Create a TV group")
def api_create_group(
    payload: GroupCreateRequest,
    user: dict[str, Any] = Depends(require_permission("group.manage")),
    _: None = Depends(api_csrf_guard),
):
    if payload.parent_id is not None:
        group_or_404(payload.parent_id)
        ensure_covers(user, "group.manage", group_id=payload.parent_id)
    else:
        # A root group belongs to nobody's branch, so creating one needs
        # authority over the whole tree.
        ensure_covers(user, "group.manage")
    if store.group_depth(payload.parent_id) >= store.MAX_GROUP_DEPTH:
        raise HTTPException(400, f"Groups cannot nest deeper than {store.MAX_GROUP_DEPTH} levels")
    try:
        schedule_values = normalize_schedule(
            payload.schedule_mode,
            payload.schedule_days,
            payload.schedule_start,
            payload.schedule_end,
        )
        group_id = store.create_group(payload.name, payload.parent_id, schedule_values)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A group with this name already exists here") from None
    store.add_event(None, "group_created", f"API created group {payload.name.strip()}", user["username"])
    push_all_node_configs()
    return {"id": group_id, "group": store.get_group(group_id)}


@app.patch("/api/v1/groups/{group_id}", tags=["groups"], summary="Rename or move a TV group")
def api_update_group(
    group_id: int,
    payload: GroupUpdateRequest,
    user: dict[str, Any] = Depends(require_api_auth),
    _: None = Depends(api_csrf_guard),
):
    group = group_or_404(group_id)
    schedule_fields = {"schedule_mode", "schedule_days", "schedule_start", "schedule_end"}
    touches_schedule = bool(payload.model_fields_set & schedule_fields)
    touches_identity = bool(payload.model_fields_set - schedule_fields)

    # Setting a branch's hours should not require the power to delete the
    # branch, so the two are governed separately over the same object.
    if touches_schedule:
        ensure_covers(user, "schedule.manage", group_id=group_id)
    if touches_identity:
        ensure_covers(user, "group.manage", group_id=group_id)
    if not touches_schedule and not touches_identity:
        ensure_covers(user, "group.manage", group_id=group_id)

    if payload.move and payload.parent_id is not None:
        group_or_404(payload.parent_id)
        ensure_covers(user, "group.manage", group_id=payload.parent_id)
        # Re-parenting a group under its own descendant would detach the
        # whole branch from the tree into an unreachable cycle.
        if payload.parent_id in store.group_subtree_ids(group_id):
            raise HTTPException(400, "A group cannot be moved inside itself")
        resulting_depth = store.group_depth(payload.parent_id) + store.group_height(group_id)
        if resulting_depth > store.MAX_GROUP_DEPTH:
            raise HTTPException(400, f"Groups cannot nest deeper than {store.MAX_GROUP_DEPTH} levels")
    schedule_values = None
    if touches_schedule:
        schedule_values = normalize_schedule(
            payload.schedule_mode if "schedule_mode" in payload.model_fields_set else group["schedule_mode"],
            payload.schedule_days if "schedule_days" in payload.model_fields_set else group["schedule_days"],
            payload.schedule_start if "schedule_start" in payload.model_fields_set else group["schedule_start"],
            payload.schedule_end if "schedule_end" in payload.model_fields_set else group["schedule_end"],
        )
    try:
        store.update_group(group_id, payload.name, payload.parent_id, payload.move, schedule_values)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A group with this name already exists here") from None
    store.add_event(None, "group_changed", f"API changed group {group_id}", user["username"])
    push_all_node_configs()
    return {"ok": True, "group": store.get_group(group_id)}


@app.delete("/api/v1/groups/{group_id}", tags=["groups"], summary="Delete a TV group and its children")
def api_delete_group(
    group_id: int,
    user: dict[str, Any] = Depends(require_permission("group.manage")),
    _: None = Depends(api_csrf_guard),
):
    group = group_or_404(group_id)
    ensure_covers(user, "group.manage", group_id=group_id)
    removed = len(store.group_subtree_ids(group_id))
    store.delete_group(group_id)
    store.add_event(None, "group_deleted", f"API deleted group {group['name']} and {removed - 1} nested", user["username"])
    push_all_node_configs()
    return {"ok": True, "removed": removed}


@app.get("/api/v1/profiles", tags=["profiles"], summary="List installed TV templates")
def api_list_profiles(_: dict[str, Any] = Depends(require_permission("template.view"))):
    installed = [public_profile(key, value) for key, value in PROFILES.items()]
    installed.sort(key=lambda item: (item["source"] != "builtin", item["name"].lower()))
    return {"profiles": installed, "in_use": sorted(set(store.distinct_tv_profiles()))}


@app.get("/api/v1/profiles/catalog", tags=["profiles"], summary="Browse the community template catalog")
def api_profile_catalog(_: dict[str, Any] = Depends(require_permission("template.view"))):
    catalog = community_catalog()
    installed = set(PROFILES)
    return {**catalog, "entries": [{**entry, "installed": entry["id"] in installed} for entry in catalog["entries"]]}


@app.post("/api/v1/profiles/install", tags=["profiles"], summary="Install a TV template by URL or catalog id")
def api_install_profile(
    payload: ProfileInstallRequest,
    user: dict[str, Any] = Depends(require_permission("template.manage")),
    _: None = Depends(api_csrf_guard),
):
    source = "url"
    url = payload.url
    template_id = payload.profile_id
    if payload.catalog_id:
        catalog = community_catalog()
        if not catalog["enabled"]:
            raise HTTPException(400, "Community catalog is disabled (SCREENLOOP_COMMUNITY_CATALOG_CHECK)")
        entry = next((item for item in catalog["entries"] if item["id"] == payload.catalog_id), None)
        if not entry:
            raise HTTPException(404, f"Template '{payload.catalog_id}' is not in the catalog")
        source, url, template_id = "catalog", entry["url"], template_id or entry["id"]
    if not url:
        raise HTTPException(400, "url or catalog_id is required")
    template_id = (template_id or id_from_url(url)).strip().lower()
    try:
        raw = fetch_template(url)
        profile = install_template(raw, template_id)
    except TemplateError as exc:
        raise HTTPException(400, {"message": "Template rejected", "errors": exc.errors}) from None
    except OSError as exc:
        raise HTTPException(507, f"Failed to store template: {exc}") from None
    store.add_event(
        None,
        "profile_installed",
        f"Installed TV template {template_id}",
        event_details(user=user["username"], source=source, url=url),
    )
    return {"profile": public_profile(template_id, profile)}


@app.post("/api/v1/profiles/upload", tags=["profiles"], summary="Upload a TV template file")
def api_upload_profile(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(require_permission("template.manage")),
    _: None = Depends(api_csrf_guard),
):
    filename = Path(file.filename or "").name
    if not filename.endswith(".toml"):
        raise HTTPException(400, "Template file must have a .toml extension")
    template_id = filename[: -len(".toml")].strip().lower()
    raw = file.file.read(MAX_TEMPLATE_BYTES + 1)
    try:
        profile = install_template(raw, template_id)
    except TemplateError as exc:
        raise HTTPException(400, {"message": "Template rejected", "errors": exc.errors}) from None
    except OSError as exc:
        raise HTTPException(507, f"Failed to store template: {exc}") from None
    store.add_event(
        None,
        "profile_installed",
        f"Installed TV template {template_id}",
        event_details(user=user["username"], source="upload", file=filename),
    )
    return {"profile": public_profile(template_id, profile)}


@app.delete("/api/v1/profiles/{profile_id}", tags=["profiles"], summary="Delete a custom TV template")
def api_delete_profile(
    profile_id: str,
    user: dict[str, Any] = Depends(require_permission("template.manage")),
    _: None = Depends(api_csrf_guard),
):
    in_use = [tv["name"] for tv in store.list_tvs() if tv.get("profile") == profile_id]
    if in_use:
        raise HTTPException(409, f"Template is assigned to: {', '.join(in_use)}")
    try:
        delete_template(profile_id)
    except TemplateError as exc:
        status = 404 if "is not installed" in exc.errors[0] else 400
        raise HTTPException(status, {"message": "Template not removed", "errors": exc.errors}) from None
    store.add_event(
        None,
        "profile_deleted",
        f"Deleted TV template {profile_id}",
        event_details(user=user["username"]),
    )
    return {"ok": True}


@app.get("/api/v1/events", tags=["events"], summary="List service and audit events")
def api_events(
    tv_id: int = 0,
    event_type: str | None = None,
    limit: int = 200,
    user: dict[str, Any] = Depends(require_permission("event.view")),
):
    safe_limit = min(max(limit, 1), 500)
    return {"events": visible_events(store.list_events(tv_id or None, event_type, safe_limit), user)}


@app.get("/api/v1/stream/events", tags=["events"], summary="Stream live status and service events with SSE")
async def api_event_stream(request: Request, _: dict[str, Any] = Depends(require_api_auth)):
    session_token = request.cookies.get("screenloop_session")

    async def stream():
        while True:
            if await request.is_disconnected():
                break
            session_user = store.get_session_user(session_token, touch=False)
            if not session_user:
                break
            snapshot = live_snapshot(session_user)
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


def require_node(request: Request) -> dict[str, Any]:
    node = store.get_node_by_token(request.headers.get("x-node-token", ""))
    if not node:
        raise HTTPException(401, "Node authentication required")
    return node


def node_tv_config_message(node_id: int) -> dict[str, Any]:
    tvs = []
    settings = store.get_playback_schedule()
    moment = schedule.now()
    for tv in store.tvs_for_node(node_id):
        items = []
        if tv.get("active_playlist_id"):
            for item in store.playlist_items(tv["active_playlist_id"]):
                media = store.get_media(item["media_id"])
                transcode_row = store.get_transcode(item["media_id"], profile_or_default(tv["profile"]))
                if not media or not transcode_row or transcode_row["status"] != "done":
                    continue
                # A node plays from this list on its own, so the lifecycle has
                # to be applied here too or a draft would reach a remote site
                # while the local worker refused it.
                if not lifecycle.playable(media):
                    continue
                items.append(
                    {
                        "media_id": item["media_id"],
                        "title": item["title"],
                        "duration_seconds": media.get("duration_seconds"),
                        "digest": hashlib.sha1(str(transcode_row["output_path"]).encode()).hexdigest()[:16],
                        "sync_path": f"/api/v1/nodes/media/{item['media_id']}/{profile_or_default(tv['profile'])}",
                    }
                )
        tvs.append(
            {
                "id": tv["id"],
                "name": tv["name"],
                "ip": tv["ip"],
                "profile": profile_or_default(tv["profile"]),
                "autoplay": bool(tv.get("autoplay")),
                "muted": bool(tv.get("muted")),
                "repeat_mode": tv.get("repeat_mode") or "all",
                "control_url": tv.get("control_url"),
                "rendering_control_url": tv.get("rendering_control_url"),
                "schedule": schedule.window_payload(schedule.resolve_window(tv, settings)),
                "items": items,
            }
        )
    profiles = {
        key: {
            "mime_type": value.get("mime_type"),
            "dlna_protocol_info": value.get("dlna_protocol_info"),
            "probe_port": value.get("probe_port"),
        }
        for key, value in PROFILES.items()
    }
    utc_offset = moment.utcoffset()
    return {
        "type": "tv_config",
        "tvs": tvs,
        "profiles": profiles,
        "schedule_timezone": config.TIMEZONE or None,
        "schedule_utc_offset": int(utc_offset.total_seconds()) if utc_offset else 0,
    }


def push_node_config(node_id: int) -> None:
    if node_hub.is_connected(node_id):
        node_hub.send(node_id, node_tv_config_message(node_id))


def push_all_node_configs() -> None:
    for node_id in node_hub.connected_ids():
        node_hub.send(node_id, node_tv_config_message(node_id))


def handle_node_message(node: dict[str, Any], message: dict[str, Any]) -> dict[str, Any] | None:
    node_id = int(node["id"])
    kind = message.get("type")
    if kind == "config_request":
        return node_tv_config_message(node_id)
    if kind == "hello":
        store.set_node_runtime(
            node_id,
            online=True,
            version=str(message.get("node_version") or ""),
            hostname=str(message.get("hostname") or ""),
        )
    elif kind == "tv_status":
        for status in message.get("tvs") or []:
            if isinstance(status, dict):
                store.apply_node_tv_status(node_id, status)
        store.set_node_runtime(node_id, online=True)
    elif kind == "command_result":
        command_id = int(message.get("command_id") or 0)
        if message.get("ok"):
            store.mark_command_done(command_id)
            store.add_event(message.get("tv_id"), "command_done", f"Node finished command {command_id}")
        else:
            error = str(message.get("error") or "node error")
            store.mark_command_failed(command_id, error)
            store.add_event(message.get("tv_id"), "command_failed", f"Node command {command_id} failed", error)
    elif kind == "scan_result":
        devices = [item for item in (message.get("devices") or []) if isinstance(item, dict)]
        node_hub.store_scan_result(node_id, devices)
    elif kind == "cache_status":
        store.set_node_runtime(node_id, cache_used_bytes=int(message.get("used_bytes") or 0))
    return None


@app.post("/api/v1/nodes", tags=["nodes"], summary="Create node and one-time enrollment token")
def api_create_node(payload: NodeCreateRequest, user: dict[str, Any] = Depends(require_permission("node.enrol")), _: None = Depends(api_csrf_guard)):
    node_id, enroll_token = store.create_node(payload.name)
    store.add_event(None, "node_created", f"API created node {payload.name.strip()}", user["username"])
    return {"id": node_id, "enroll_token": enroll_token}


@app.get("/api/v1/nodes", tags=["nodes"], summary="List nodes")
def api_list_nodes(user: dict[str, Any] = Depends(require_permission("node.view"))):
    scopes = scopes_for(user)
    nodes = [node for node in store.list_nodes() if scopes.covers("node.view", node_id=int(node["id"]))]
    for node in nodes:
        node["connected"] = node_hub.is_connected(int(node["id"]))
    return {"nodes": nodes}


@app.patch("/api/v1/nodes/{node_id}", tags=["nodes"], summary="Rename node")
def api_rename_node(
    node_id: int,
    payload: NodeRenameRequest,
    user: dict[str, Any] = Depends(require_permission("node.manage")),
    _: None = Depends(api_csrf_guard),
):
    if not store.get_node(node_id):
        raise HTTPException(404, "Node not found")
    ensure_covers(user, "node.manage", node_id=node_id)
    store.rename_node(node_id, payload.name)
    return {"ok": True}


@app.delete("/api/v1/nodes/{node_id}", tags=["nodes"], summary="Revoke and delete node")
def api_delete_node(node_id: int, user: dict[str, Any] = Depends(require_permission("node.enrol")), _: None = Depends(api_csrf_guard)):
    node = store.get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    ensure_covers(user, "node.manage", node_id=node_id)
    store.mark_node_tvs_unreachable(node_id)
    store.delete_node(node_id)
    store.add_event(None, "node_deleted", f"API deleted node {node['name']}", user["username"])
    return {"ok": True}


@app.post("/api/v1/nodes/{node_id}/scan", tags=["nodes"], summary="Scan the node's network for TVs")
async def api_node_scan(
    node_id: int,
    user: dict[str, Any] = Depends(require_permission("node.manage")),
    __: None = Depends(api_csrf_guard),
):
    if not store.get_node(node_id):
        raise HTTPException(404, "Node not found")
    ensure_covers(user, "node.manage", node_id=node_id)
    if not node_hub.is_connected(node_id):
        raise HTTPException(502, "Node is offline")
    requested_at = time.time()
    node_hub.send(node_id, {"type": "scan"})
    for _attempt in range(16):
        await asyncio.sleep(0.5)
        devices = node_hub.scan_result_since(node_id, requested_at)
        if devices is not None:
            existing = {tv["ip"] for tv in store.tvs_for_node(node_id)}
            for item in devices:
                item["profile"] = detect_profile(item.get("manufacturer"), item.get("model_name"), item.get("friendly_name"))
                item["configured"] = item.get("ip") in existing
            return {"devices": devices, "profiles": PROFILES}
    raise HTTPException(504, "Node scan timed out")


@app.post("/api/v1/nodes/enroll", tags=["nodes"], summary="Exchange a one-time enrollment token for a node token")
def api_node_enroll(request: Request, payload: NodeEnrollRequest):
    ip = client_ip(request)
    enroll_key = f"node-enroll:{ip}"
    if rate_limited(_auth_failures, enroll_key, 10, 300):
        raise HTTPException(429, "Too many enrollment attempts")
    claimed = store.claim_node_enrollment(payload.enroll_token)
    if not claimed:
        record_failure(_auth_failures, enroll_key)
        store.add_event(None, "node_enroll_failed", "Node enrollment failed", ip)
        raise HTTPException(403, "Invalid or expired enrollment token")
    store.add_event(None, "node_enrolled", f"Node {claimed['name']} enrolled", ip)
    return claimed


@app.get("/api/v1/nodes/media/{media_id}/{profile}", tags=["nodes"], summary="Download a transcoded file (node token)")
def api_node_media(media_id: int, profile: str, request: Request):
    require_node(request)
    transcode_row = store.get_transcode(media_id, profile_or_default(profile))
    if not transcode_row or transcode_row["status"] != "done" or not transcode_row["output_path"]:
        raise HTTPException(404, "Transcode is not ready")
    path = Path(transcode_row["output_path"])
    if not path.exists():
        raise HTTPException(404, "Transcoded file not found")
    return ranged_file_response(path, request, send_body=request.method != "HEAD")


@app.websocket("/api/v1/nodes/ws")
async def api_node_ws(websocket: WebSocket):
    token = websocket.headers.get("authorization", "").removeprefix("Bearer").strip()
    node = store.get_node_by_token(token)
    if not node:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    node_id = int(node["id"])
    node_hub.attach(node_id, websocket, asyncio.get_running_loop())
    store.set_node_runtime(node_id, online=True)
    store.add_event(None, "node_connected", f"Node {node['name']} connected")
    try:
        await websocket.send_text(json.dumps(node_tv_config_message(node_id)))
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                reply = handle_node_message(node, message)
                if reply is not None:
                    await websocket.send_text(json.dumps(reply))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("node %s websocket error: %s", node_id, exc)
    finally:
        node_hub.detach(node_id, websocket)
        if store.get_node(node_id):
            store.set_node_runtime(node_id, online=False)
            store.mark_node_tvs_unreachable(node_id)
        store.add_event(None, "node_disconnected", f"Node {node['name']} disconnected")


@app.get("/api/v1/users", tags=["users"], summary="List users")
def api_users(_: dict[str, Any] = Depends(require_permission("user.manage"))):
    return {"users": store.list_users()}


@app.post("/api/v1/users", tags=["users"], summary="Create user")
def api_create_user(payload: UserCreateRequest, user: dict[str, Any] = Depends(require_permission("user.manage")), _: None = Depends(api_csrf_guard)):
    require_password_strength(payload.password)
    ensure_may_grant(user, permissions.BUILTIN_ROLES.get(payload.role, frozenset()))
    user_id = store.create_user(payload.username.strip(), payload.password, payload.role)
    store.add_event(None, "user_created", f"API created user {payload.username.strip()} as {payload.role}", user["username"])
    return {"id": user_id, "user": store.get_user(user_id)}


@app.patch("/api/v1/users/{user_id}", tags=["users"], summary="Update user role/status")
def api_update_user(
    user_id: int,
    payload: UserUpdateRequest,
    user: dict[str, Any] = Depends(require_permission("user.manage")),
    _: None = Depends(api_csrf_guard),
):
    if user_id == user["id"] and payload.disabled:
        raise HTTPException(400, "You cannot disable your own user")
    target = store.get_user(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if target["role"] != payload.role:
        ensure_may_grant(user, permissions.BUILTIN_ROLES.get(payload.role, frozenset()))
    demotes_admin = target["role"] == "admin" and (payload.role != "admin" or payload.disabled)
    if demotes_admin and store.count_active_admins(exclude_user_id=user_id) == 0:
        raise HTTPException(400, "Cannot demote or disable the last active admin")
    store.update_user(user_id, payload.role, payload.disabled)
    store.add_event(None, "user_updated", f"API updated user {user_id}", user["username"])
    return {"ok": True, "user": store.get_user(user_id)}


@app.get("/api/v1/permissions", tags=["roles"], summary="List the permission catalogue")
def api_list_permissions(_: dict[str, Any] = Depends(require_any_permission("role.view", "role.manage"))):
    return {
        "permissions": [
            {
                "key": permission.key,
                "section": permission.section,
                "title": permission.title,
                "description": permission.description,
            }
            for permission in permissions.CATALOG
        ]
    }


@app.get("/api/v1/roles", tags=["roles"], summary="List roles")
def api_list_roles(_: dict[str, Any] = Depends(require_any_permission("role.view", "role.manage"))):
    # Reading the roles table is its own permission: an auditor needs to see
    # what authority has been handed out without being able to hand out more.
    # role.manage still gets in, so nobody who could read this list before lost
    # it -- including a branch administrator, whose role.manage is scoped.
    return {"roles": store.list_roles()}


@app.post("/api/v1/roles", tags=["roles"], summary="Create a role")
def api_create_role(
    payload: RoleRequest,
    user: dict[str, Any] = Depends(require_permission("role.manage")),
    _: None = Depends(api_csrf_guard),
):
    name = payload.name.strip()
    if name in permissions.SEEDED_ROLES:
        raise HTTPException(400, "That name belongs to a built-in role")
    if store.get_role_by_name(name):
        raise HTTPException(409, "A role with that name already exists")
    wanted = ensure_known_permissions(payload.permissions)
    ensure_may_grant(user, wanted)
    role_id = store.create_role(name, payload.description.strip(), wanted)
    store.add_event(None, "role_created", f"Created role {name}", user["username"])
    return {"id": role_id, "role": store.get_role(role_id)}


@app.patch("/api/v1/roles/{role_id}", tags=["roles"], summary="Update a role")
def api_update_role(
    role_id: int,
    payload: RoleRequest,
    user: dict[str, Any] = Depends(require_permission("role.manage")),
    _: None = Depends(api_csrf_guard),
):
    role = role_or_404(role_id)
    ensure_role_is_editable(role)
    name = payload.name.strip()
    if name in permissions.SEEDED_ROLES:
        raise HTTPException(400, "That name belongs to a built-in role")
    existing = store.get_role_by_name(name)
    if existing and int(existing["id"]) != role_id:
        raise HTTPException(409, "A role with that name already exists")
    wanted = ensure_known_permissions(payload.permissions)
    # Both directions matter: you may not add authority you lack, and you may
    # not strip authority the installation still needs somebody to hold.
    ensure_may_grant(user, wanted - permissions.normalise(role["permissions"]))
    ensure_authority_survives(role_id, wanted)
    store.update_role(role_id, name, payload.description.strip(), wanted)
    store.add_event(None, "role_updated", f"Updated role {name}", user["username"])
    return {"ok": True, "role": store.get_role(role_id)}


@app.delete("/api/v1/roles/{role_id}", tags=["roles"], summary="Delete a role")
def api_delete_role(
    role_id: int,
    user: dict[str, Any] = Depends(require_permission("role.manage")),
    _: None = Depends(api_csrf_guard),
):
    role = role_or_404(role_id)
    ensure_role_is_editable(role)
    ensure_authority_survives(role_id, frozenset())
    store.delete_role(role_id)
    store.add_event(None, "role_deleted", f"Deleted role {role['name']}", user["username"])
    return {"ok": True}


@app.put("/api/v1/users/{user_id}/roles", tags=["roles"], summary="Set the roles a user holds")
def api_set_user_roles(
    user_id: int,
    payload: UserRolesRequest,
    user: dict[str, Any] = Depends(require_permission("role.manage")),
    _: None = Depends(api_csrf_guard),
):
    if not store.get_user(user_id):
        raise HTTPException(404, "User not found")

    scopes = scopes_for(user)
    wanted: frozenset[str] = frozenset()
    entries: list[dict[str, Any]] = []
    for assignment in payload.assignments:
        role = role_or_404(assignment.role_id)
        granted = permissions.normalise(role["permissions"])
        scope_type = assignment.scope_type
        if scope_type not in permissions.SCOPE_TYPES:
            raise HTTPException(400, f"scope_type must be one of {', '.join(permissions.SCOPE_TYPES)}")
        scope_id = assignment.scope_id if scope_type != permissions.GLOBAL else None
        if scope_type != permissions.GLOBAL and scope_id is None:
            raise HTTPException(400, "A group or node scope needs scope_id")
        if scope_type == permissions.GROUP and not store.get_group(scope_id or 0):
            raise HTTPException(404, "Group not found")
        if scope_type == permissions.NODE and not store.get_node(scope_id or 0):
            raise HTTPException(404, "Node not found")

        # A whole-installation permission narrowed to a branch would be
        # silently inert: the gate demands a global grant and would refuse it.
        # Better to refuse the assignment than to hand somebody a role that
        # looks like it works.
        if scope_type != permissions.GLOBAL:
            misplaced = sorted(granted & permissions.GLOBAL_ONLY)
            if misplaced:
                raise HTTPException(
                    400,
                    f"These apply to the whole installation and cannot be granted to a {scope_type}: "
                    f"{', '.join(misplaced)}",
                )

        # You may not hand out authority over an object you have none over.
        # Granting tv.manage on a branch requires holding it globally or on
        # that branch, so a branch administrator cannot widen their own reach
        # by granting themselves a role somewhere else.
        for permission in sorted(granted):
            covered = (
                scopes.covers(permission)
                if scope_type == permissions.GLOBAL
                else scopes.covers(
                    permission,
                    group_id=scope_id if scope_type == permissions.GROUP else None,
                    node_id=scope_id if scope_type == permissions.NODE else None,
                )
            )
            if not covered:
                raise HTTPException(403, f"You cannot grant {permission} at that scope")

        wanted |= granted if scope_type == permissions.GLOBAL else frozenset()
        entries.append({"role_id": assignment.role_id, "scope_type": scope_type, "scope_id": scope_id})

    # Losing a role can strip the last administrator just as surely as editing
    # one can, so the same invariant is checked against the resulting set. Only
    # a global grant counts: an administrator confined to one branch cannot
    # administer the installation.
    for permission in ADMINISTRATIVE_PERMISSIONS:
        if permission in wanted:
            continue
        holders = set(store.users_with_global_permission(permission)) - {user_id}
        if not holders:
            raise HTTPException(400, f"This would leave nobody holding {permission}")

    store.set_user_roles(user_id, entries)
    store.add_event(None, "user_roles_changed", f"Changed roles of user {user_id}", user["username"])
    return {"ok": True, "roles": store.user_roles(user_id), "permissions": sorted(store.user_permissions(user_id))}


def ensure_known_permissions(keys: list[str]) -> frozenset[str]:
    unknown = sorted({str(key) for key in keys} - permissions.KEYS)
    if unknown:
        raise HTTPException(400, f"Unknown permissions: {', '.join(unknown)}")
    return permissions.normalise(keys)


@app.post("/api/v1/users/{user_id}/password", tags=["users"], summary="Change user password")
def api_change_user_password(
    user_id: int,
    payload: PasswordChangeRequest,
    user: dict[str, Any] = Depends(require_permission("user.manage")),
    _: None = Depends(api_csrf_guard),
):
    if not store.get_user(user_id):
        raise HTTPException(404, "User not found")
    actor = store.get_user_by_username(user["username"])
    if not actor or not verify_password(payload.admin_password, actor.get("password_hash")):
        store.add_event(None, "user_password_change_denied", f"Admin password confirmation failed for {user['username']}")
        raise HTTPException(403, "Admin password confirmation failed")
    require_password_strength(payload.password)
    store.set_user_password(user_id, payload.password)
    store.add_event(None, "user_password_changed", f"API changed password for user {user_id}", user["username"])
    return {"ok": True}


@app.get("/api/health", tags=["health"], summary="Public healthcheck")
def api_health():
    return {"status": "ok"}


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
    # SetNextAVTransportURI hands the TV a clip to play by itself, so the same
    # rule the worker applies has to hold here.
    if not lifecycle.playable(store.get_media(item["media_id"])):
        return False
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
    if not verify_stream_token(media_id, profile, token, client_ip(request)):
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
    logger.info("%s tv=%s media=%s; queueing next", event_type, tv["id"], media_id)
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

    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run("screenloop.web:app", host=config.HTTP_HOST, port=config.HTTP_PORT, access_log=config.ACCESS_LOG)


if __name__ == "__main__":
    main()
