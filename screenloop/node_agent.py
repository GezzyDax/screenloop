"""Screenloop node agent: controls TVs in a remote LAN on behalf of a controller.

Runs with `python -m screenloop.node_agent`. Keeps an outbound websocket to the
controller, caches transcoded media locally, serves /stream to its TVs, and
keeps playlists looping even while the controller is unreachable.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import APP_VERSION
from .dlna import discover_device, get_local_ip_for, host_ping_reachable, push_video, set_mute, stop_strict
from .httprange import iter_file_range, range_response_parts

logger = logging.getLogger("screenloop.node")

CONTROLLER_URL = os.environ.get("SCREENLOOP_NODE_CONTROLLER_URL", "").rstrip("/")
ENROLL_TOKEN = os.environ.get("SCREENLOOP_NODE_ENROLL_TOKEN", "")
DATA_DIR = Path(os.environ.get("SCREENLOOP_NODE_DATA_DIR", str(Path.home() / ".local" / "share" / "screenloop-node")))
HTTP_PORT = int(os.environ.get("SCREENLOOP_NODE_HTTP_PORT", "8099"))
ADVERTISE_HOST = os.environ.get("SCREENLOOP_NODE_ADVERTISE_HOST", "")
CACHE_BYTES = int(os.environ.get("SCREENLOOP_NODE_CACHE_BYTES", str(10 * 1024 * 1024 * 1024)))
POLL_INTERVAL = float(os.environ.get("SCREENLOOP_NODE_POLL_INTERVAL", "3"))
SYNC_INTERVAL = float(os.environ.get("SCREENLOOP_NODE_SYNC_INTERVAL", "30"))
STREAM_TOKEN_TTL = int(os.environ.get("SCREENLOOP_NODE_STREAM_TOKEN_TTL", str(6 * 60 * 60)))
AUTO_ADVANCE_END_GRACE = 5
UNKNOWN_DURATION_AFTER = 60

TOKEN_FILE = DATA_DIR / "node.token"
CACHE_DIR = DATA_DIR / "cache"


class NodeAgent:
    def __init__(self) -> None:
        self.token = ""
        self.tvs: dict[int, dict[str, Any]] = {}
        self.profiles: dict[str, dict[str, Any]] = {}
        self.runtime: dict[int, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.tv_locks: dict[int, threading.RLock] = {}
        self.ws: Any = None
        self.loop: asyncio.AbstractEventLoop | None = None

    def tv_lock(self, tv_id: int) -> threading.RLock:
        return self.tv_locks.setdefault(tv_id, threading.RLock())

    # ----- enrollment / identity -----

    def ensure_token(self) -> str:
        if TOKEN_FILE.exists():
            token = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if token:
                return token
        if not ENROLL_TOKEN:
            raise RuntimeError("No node token found; set SCREENLOOP_NODE_ENROLL_TOKEN for first start")
        payload = self._enroll_with_retry()
        token = str(payload["token"])
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(token, encoding="utf-8")
        try:
            TOKEN_FILE.chmod(0o600)
        except OSError:
            pass
        logger.info("enrolled as node %s (%s)", payload.get("node_id"), payload.get("name"))
        return token

    def _enroll_with_retry(self) -> dict[str, Any]:
        delay = 2.0
        while True:
            request = urllib.request.Request(
                f"{CONTROLLER_URL}/api/v1/nodes/enroll",
                data=json.dumps({"enroll_token": ENROLL_TOKEN}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    raise RuntimeError(f"Enrollment rejected by controller: HTTP {exc.code}") from exc
                logger.warning("controller returned HTTP %s during enrollment, retrying in %.0fs", exc.code, delay)
            except Exception as exc:
                logger.warning("failed to reach controller for enrollment (%s), retrying in %.0fs", exc, delay)
            time.sleep(delay)
            delay = min(60.0, delay * 2)

    # ----- stream token signing (keyed by the node token) -----

    def sign_stream(self, media_id: int, profile: str, client_ip: str, expires_at: int) -> str:
        payload = f"{media_id}:{profile}:{client_ip}:{expires_at}"
        return hmac.new(self.token.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def stream_url(self, tv_ip: str, media_id: int, profile: str) -> str:
        expires_at = int(time.time()) + STREAM_TOKEN_TTL
        signature = self.sign_stream(media_id, profile, tv_ip, expires_at)
        host = ADVERTISE_HOST or get_local_ip_for(tv_ip)
        return f"http://{host}:{HTTP_PORT}/stream/{media_id}?profile={profile}&token={expires_at}:{signature}"

    def verify_stream(self, media_id: int, profile: str, token: str, client_ip: str) -> bool:
        parts = (token or "").split(":", 1)
        if len(parts) != 2:
            return False
        expires_at, signature = parts
        try:
            if int(expires_at) < time.time():
                return False
        except ValueError:
            return False
        expected = self.sign_stream(media_id, profile, client_ip, int(expires_at))
        return hmac.compare_digest(signature, expected)

    # ----- cache -----

    def cache_path(self, media_id: int, profile: str, digest: str) -> Path:
        return CACHE_DIR / f"{media_id}.{profile}.{digest}.mp4"

    def cached_file(self, media_id: int, profile: str) -> Path | None:
        for path in CACHE_DIR.glob(f"{media_id}.{profile}.*.mp4"):
            if path.stat().st_size > 0:
                return path
        return None

    def wanted_cache_items(self) -> list[dict[str, Any]]:
        wanted = []
        with self.lock:
            tvs = list(self.tvs.values())
        for tv in tvs:
            for item in tv.get("items") or []:
                wanted.append({**item, "profile": tv["profile"]})
        return wanted

    def sync_cache_once(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        wanted = self.wanted_cache_items()
        keep_names = set()
        for item in wanted:
            target = self.cache_path(item["media_id"], item["profile"], item["digest"])
            keep_names.add(target.name)
            if target.exists() and target.stat().st_size > 0:
                continue
            self.download_media(item, target)
        self.prune_cache(keep_names)
        self.send_ws({"type": "cache_status", "used_bytes": self.cache_used_bytes()})

    def download_media(self, item: dict[str, Any], target: Path) -> None:
        url = f"{CONTROLLER_URL}{item['sync_path']}"
        tmp = target.with_name(target.name + ".tmp")
        request = urllib.request.Request(url, headers={"X-Node-Token": self.token})
        try:
            with urllib.request.urlopen(request, timeout=60) as response, tmp.open("wb") as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            tmp.replace(target)
            logger.info("cached media %s (%s)", item["media_id"], item["profile"])
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            logger.warning("failed to cache media %s: %s", item["media_id"], exc)

    def cache_used_bytes(self) -> int:
        return sum(path.stat().st_size for path in CACHE_DIR.glob("*.mp4") if path.is_file())

    def prune_cache(self, keep_names: set[str]) -> None:
        files = [path for path in CACHE_DIR.glob("*.mp4") if path.is_file()]
        total = sum(path.stat().st_size for path in files)
        if total <= CACHE_BYTES:
            # Still drop files that no longer belong to any playlist.
            for path in files:
                if path.name not in keep_names:
                    path.unlink(missing_ok=True)
            return
        for path in sorted(files, key=lambda item: item.stat().st_atime):
            if total <= CACHE_BYTES:
                break
            if path.name in keep_names:
                continue
            total -= path.stat().st_size
            path.unlink(missing_ok=True)

    # ----- config / websocket -----

    def apply_config(self, message: dict[str, Any]) -> None:
        with self.lock:
            self.profiles = message.get("profiles") or {}
            fresh: dict[int, dict[str, Any]] = {}
            for tv in message.get("tvs") or []:
                tv_id = int(tv["id"])
                fresh[tv_id] = tv
                self.runtime.setdefault(tv_id, {"index": 0, "media_id": None, "started_at": 0, "control_url": tv.get("control_url")})
                if tv.get("control_url"):
                    self.runtime[tv_id]["control_url"] = tv["control_url"]
            self.tvs = fresh
            for tv_id in list(self.runtime):
                if tv_id not in fresh:
                    self.runtime.pop(tv_id, None)
        logger.info("applied config: %s TVs", len(self.tvs))

    def send_ws(self, message: dict[str, Any]) -> bool:
        websocket = self.ws
        loop = self.loop
        if websocket is None or loop is None:
            return False
        try:
            asyncio.run_coroutine_threadsafe(websocket.send(json.dumps(message)), loop).result(timeout=5)
            return True
        except Exception:
            return False

    async def ws_loop(self) -> None:
        import websockets

        ws_url = CONTROLLER_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/v1/nodes/ws"
        delay = 2.0
        while True:
            try:
                async with websockets.connect(ws_url, additional_headers={"Authorization": f"Bearer {self.token}"}) as websocket:
                    self.ws = websocket
                    delay = 2.0
                    await websocket.send(json.dumps({"type": "hello", "node_version": APP_VERSION, "hostname": socket.gethostname()}))
                    logger.info("connected to controller")
                    async for raw in websocket:
                        try:
                            message = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        await asyncio.get_running_loop().run_in_executor(None, self.handle_message, message)
            except Exception as exc:
                logger.warning("controller connection lost: %s", exc)
            finally:
                self.ws = None
            await asyncio.sleep(delay)
            delay = min(60.0, delay * 2)

    def handle_message(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "tv_config":
            self.apply_config(message)
        elif kind == "command":
            self.run_command(message)
        elif kind == "scan":
            self.run_scan()

    # ----- TV control -----

    def tv_profile(self, tv: dict[str, Any]) -> dict[str, Any]:
        return self.profiles.get(tv.get("profile") or "", {}) or {}

    def ensure_control_url(self, tv: dict[str, Any], force: bool = False) -> str:
        state = self.runtime[int(tv["id"])]
        if state.get("control_url") and not force:
            return str(state["control_url"])
        info = discover_device(tv["ip"], get_local_ip_for(tv["ip"]))
        state["control_url"] = info["control_url"]
        state["rendering_control_url"] = info.get("rendering_control_url")
        return str(info["control_url"])

    def playable_items(self, tv: dict[str, Any]) -> list[dict[str, Any]]:
        items = []
        for item in tv.get("items") or []:
            if self.cached_file(item["media_id"], tv["profile"]):
                items.append(item)
        return items

    def push_next(self, tv: dict[str, Any]) -> None:
        tv_id = int(tv["id"])
        with self.tv_lock(tv_id):
            items = self.playable_items(tv)
            if not items:
                logger.info("tv %s: no cached items to play", tv_id)
                return
            state = self.runtime[tv_id]
            index = int(state.get("index") or 0) % len(items)
            item = items[index]
            profile = self.tv_profile(tv)
            control_url = self.ensure_control_url(tv)
            url = self.stream_url(tv["ip"], item["media_id"], tv["profile"])
            try:
                push_video(
                    control_url,
                    url,
                    item["title"],
                    str(profile.get("mime_type") or "video/mp4"),
                    protocol_info=profile.get("dlna_protocol_info"),
                )
            except Exception:
                # Cached control_url may be stale (TV rebooted/woke on a new port); force
                # rediscovery on the next attempt instead of retrying a dead endpoint forever.
                state["control_url"] = None
                raise
            state["media_id"] = item["media_id"]
            state["duration"] = item.get("duration_seconds") or 0
            state["started_at"] = time.time()
            state["index"] = (index + 1) % len(items) if tv.get("repeat_mode", "all") == "all" else min(index + 1, len(items))
            if tv.get("muted"):
                try:
                    rc_url = self.runtime[tv_id].get("rendering_control_url")
                    if rc_url:
                        set_mute(str(rc_url), True)
                except Exception:
                    pass
            logger.info("tv %s: pushed media %s", tv_id, item["media_id"])

    def run_command(self, message: dict[str, Any]) -> None:
        command_id = message.get("command_id")
        tv_id = int(message.get("tv_id") or 0)
        action = str(message.get("action") or "")
        with self.lock:
            tv = self.tvs.get(tv_id)
        result: dict[str, Any] = {"type": "command_result", "command_id": command_id, "tv_id": tv_id, "ok": True}
        try:
            if not tv:
                raise RuntimeError("TV is not assigned to this node")
            with self.tv_lock(tv_id):
                state = self.runtime.get(tv_id)
                if state is None:
                    raise RuntimeError("TV is not assigned to this node")
                if action == "play_next":
                    self.push_next(tv)
                elif action == "stop":
                    stop_strict(self.ensure_control_url(tv))
                    state["media_id"] = None
                    state["started_at"] = 0
                elif action == "restart_playlist":
                    state["index"] = 0
                    self.push_next(tv)
                elif action == "rediscover":
                    self.ensure_control_url(tv, force=True)
                elif action in {"mute", "unmute"}:
                    self.ensure_control_url(tv)
                    rc_url = state.get("rendering_control_url")
                    if not rc_url:
                        raise RuntimeError("RenderingControl not advertised")
                    set_mute(str(rc_url), action == "mute")
                else:
                    raise RuntimeError(f"Unknown command: {action}")
        except Exception as exc:
            result.update({"ok": False, "error": str(exc)})
        self.send_ws(result)

    def run_scan(self) -> None:
        from .dlna import discover_renderers

        try:
            bind_ip = get_local_ip_for("239.255.255.250")
            devices = discover_renderers(bind_ip)
        except Exception as exc:
            logger.warning("scan failed: %s", exc)
            devices = []
        self.send_ws({"type": "scan_result", "devices": devices})

    # ----- polling / offline autoplay -----

    def poll_once(self) -> None:
        with self.lock:
            tvs = list(self.tvs.values())
        statuses = []
        for tv in tvs:
            statuses.append(self.poll_tv(tv))
        if statuses:
            self.send_ws({"type": "tv_status", "tvs": statuses})

    def poll_tv(self, tv: dict[str, Any]) -> dict[str, Any]:
        tv_id = int(tv["id"])
        ping_ok = host_ping_reachable(tv["ip"])
        with self.tv_lock(tv_id):
            state = self.runtime.get(tv_id)
            if state is None:
                return {"tv_id": tv_id, "online": ping_ok, "ping_reachable": ping_ok, "state": "OFFLINE", "streaming": False}
            status: dict[str, Any] = {
                "tv_id": tv_id,
                "online": ping_ok,
                "ping_reachable": ping_ok,
                "state": "OFFLINE" if not ping_ok else "PLAYING" if state.get("media_id") else "STOPPED",
                "streaming": bool(state.get("media_id")) and ping_ok,
                "current_media_id": state.get("media_id"),
                "current_index": state.get("index") or 0,
                "playback_started_at": int(state.get("started_at") or 0) or None,
            }
            if not ping_ok:
                return status
            if tv.get("autoplay"):
                self.maybe_autoplay(tv, state)
            return status

    def maybe_autoplay(self, tv: dict[str, Any], state: dict[str, Any]) -> None:
        now = time.time()
        started_at = float(state.get("started_at") or 0)
        duration = float(state.get("duration") or 0)
        if not state.get("media_id"):
            self.safe_push(tv)
            return
        threshold = duration + AUTO_ADVANCE_END_GRACE if duration > 0 else UNKNOWN_DURATION_AFTER
        if started_at and now - started_at >= threshold:
            self.safe_push(tv)

    def safe_push(self, tv: dict[str, Any]) -> None:
        try:
            self.push_next(tv)
        except Exception as exc:
            logger.warning("tv %s push failed: %s", tv.get("id"), exc)

    async def poll_loop(self) -> None:
        while True:
            await asyncio.get_running_loop().run_in_executor(None, self.poll_once)
            await asyncio.sleep(POLL_INTERVAL)

    async def sync_loop(self) -> None:
        while True:
            await asyncio.get_running_loop().run_in_executor(None, self.sync_cache_once)
            await asyncio.sleep(SYNC_INTERVAL)

    # ----- local stream server -----

    def build_app(self):
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import StreamingResponse

        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @app.get("/api/health")
        def health():
            return {"status": "ok"}

        @app.get("/stream/{media_id}")
        @app.head("/stream/{media_id}")
        def stream(media_id: int, request: Request, profile: str = "generic_dlna", token: str = ""):
            client_ip = request.client.host if request.client else ""
            if not self.verify_stream(media_id, profile, token, client_ip):
                raise HTTPException(403, "Invalid stream token")
            path = self.cached_file(media_id, profile)
            if not path:
                raise HTTPException(404, "Media is not cached on this node")
            status_code, headers, start, length = range_response_parts(path, request.headers.get("range"))
            if status_code == 416:
                return StreamingResponse(iter(()), status_code=416, headers=headers)
            if request.method == "HEAD":
                return StreamingResponse(iter(()), status_code=status_code, headers=headers)
            return StreamingResponse(iter_file_range(path, start, length), status_code=status_code, headers=headers)

        return app

    async def run(self) -> None:
        import uvicorn

        self.loop = asyncio.get_running_loop()
        server = uvicorn.Server(uvicorn.Config(self.build_app(), host="0.0.0.0", port=HTTP_PORT, log_level="warning"))
        await asyncio.gather(server.serve(), self.ws_loop(), self.poll_loop(), self.sync_loop())


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, os.environ.get("SCREENLOOP_LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not CONTROLLER_URL:
        raise SystemExit("SCREENLOOP_NODE_CONTROLLER_URL is required")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    agent = NodeAgent()
    agent.token = agent.ensure_token()
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
