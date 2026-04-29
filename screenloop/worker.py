import threading
import time
from ipaddress import ip_address, ip_network
from pathlib import Path

from . import config
from .dlna import (
    RESTART_STATES,
    discover_device,
    get_local_ip_for,
    get_transport_state,
    host_ping_reachable,
    push_video,
    stop_strict,
    tv_is_reachable,
)
from .profiles import PROFILES, detect_profile, profile_or_default
from .security import stream_query
from .store import Store
from .transcode import output_path, probe_duration_seconds, transcode


class Worker:
    def __init__(self, store: Store):
        self.store = store
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None
        self._transcode_thread: threading.Thread | None = None
        self._push_locks: dict[int, threading.Lock] = {}
        self._last_push_at: dict[int, float] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run_commands, name="screenloop-command-worker", daemon=True)
        self._thread.start()
        self._poll_thread = threading.Thread(target=self.run_poll, name="screenloop-poll-worker", daemon=True)
        self._poll_thread.start()
        self._transcode_thread = threading.Thread(target=self.run_transcode, name="screenloop-transcode-worker", daemon=True)
        self._transcode_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
        if self._transcode_thread:
            self._transcode_thread.join(timeout=5)

    def run_commands(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_tv_command()
            except Exception as exc:
                print(f"[worker] command loop error: {exc}", flush=True)
            self._stop.wait(1)

    def run_poll(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_duration_probe()
                self.poll_tvs()
            except Exception as exc:
                print(f"[worker] poll loop error: {exc}", flush=True)
            self._stop.wait(3)

    def run_transcode(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_transcode_job()
            except Exception as exc:
                print(f"[worker] transcode loop error: {exc}", flush=True)
            self._stop.wait(1)

    def process_duration_probe(self) -> None:
        media = self.store.next_media_missing_duration()
        if not media:
            return
        duration = probe_duration_seconds(Path(media["original_path"]))
        self.store.set_media_duration(media["id"], duration or 0)
        if duration:
            self.store.add_event(None, "media_duration", f"Detected duration for media {media['id']}", str(duration))

    def process_transcode_job(self) -> None:
        job = self.store.next_transcode_job()
        if not job:
            return
        self.store.mark_job_running(job["id"])
        try:
            out = transcode(Path(job["original_path"]), job["profile"])
            self.store.mark_job_done(job["id"], job["media_id"], out)
            self.store.add_event(None, "transcode_done", f"Transcoded media {job['media_id']} for {job['profile']}", str(out))
        except Exception as exc:
            self.store.mark_job_failed(job["id"], job["media_id"], str(exc))
            self.store.add_event(None, "transcode_failed", f"Transcode failed for media {job['media_id']} / {job['profile']}", str(exc))

    def process_tv_command(self) -> None:
        command = self.store.next_pending_command()
        if not command:
            return
        self.store.mark_command_running(command["id"])
        self.store.add_event(command["tv_id"], "command_started", f"Started {command['command']}")
        try:
            self.execute_command(command)
            self.store.mark_command_done(command["id"])
            self.store.add_event(command["tv_id"], "command_done", f"Finished {command['command']}")
        except Exception as exc:
            self.store.mark_command_failed(command["id"], str(exc))
            self.store.set_tv_error(command["tv_id"], f"{command['command']} failed: {exc}")
            self.store.add_event(command["tv_id"], "command_failed", f"{command['command']} failed", str(exc))

    def execute_command(self, command: dict) -> None:
        tv = self.store.get_tv(command["tv_id"])
        if not tv:
            raise RuntimeError("TV not found")
        action = command["command"]
        if action == "play_next":
            self.push_next(tv)
        elif action == "stop":
            self.stop_tv(tv)
        elif action == "restart_playlist":
            self.store.set_tv_playback_position(tv["id"], 0, None)
            self.push_next(self.store.get_tv(tv["id"]) or tv)
        elif action == "rediscover":
            self.store.clear_tv_control_url(tv["id"], "Rediscover requested")
            self.try_recover_tv(self.store.get_tv(tv["id"]) or tv)
        elif action == "rebuild_transcode":
            raise RuntimeError("rebuild_transcode is handled by web/store")
        else:
            raise RuntimeError(f"Unknown command: {action}")

    def poll_tvs(self) -> None:
        for tv in self.store.list_tvs():
            self.poll_tv(tv)

    def poll_tv(self, tv: dict) -> None:
        try:
            self.store.update_tv_health(tv["id"], ping_reachable=host_ping_reachable(tv["ip"]))
            if not tv.get("control_url"):
                self.try_recover_tv(tv)
                tv = self.store.get_tv(tv["id"]) or tv
                if not tv.get("control_url"):
                    return

            profile = PROFILES[profile_or_default(tv["profile"])]
            probe_port = _port_from_url(tv["control_url"], int(profile.get("probe_port", 9197)))
            dlna_reachable = tv_is_reachable(tv["ip"], probe_port)
            self.store.update_tv_health(tv["id"], dlna_reachable=dlna_reachable)
            if not dlna_reachable:
                self.store.clear_tv_control_url(tv["id"], f"Probe port {probe_port} is not reachable")
                return

            control_url = self.ensure_control_url(tv)
            state = get_transport_state(control_url)
            self.store.update_tv_status(tv["id"], True, state)
            if tv["autoplay"] and tv["active_playlist_id"] and state in RESTART_STATES:
                self.store.enqueue_command(tv["id"], "play_next")
        except Exception as exc:
            self.store.update_tv_health(tv["id"], soap_ready=False, streaming=False)
            self.store.clear_tv_control_url(tv["id"], str(exc))

    def try_recover_tv(self, tv: dict) -> None:
        try:
            self.ensure_control_url(tv, force=True)
            fresh_tv = self.store.get_tv(tv["id"]) or tv
            self.store.add_event(tv["id"], "tv_found", f"TV found: {fresh_tv.get('control_url')}")
            self.store.update_tv_health(tv["id"], dlna_reachable=True, soap_ready=True)
            self.store.update_tv_status(tv["id"], True, "ONLINE")
            if fresh_tv.get("autoplay") and fresh_tv.get("active_playlist_id"):
                self.store.enqueue_command(tv["id"], "play_next")
        except Exception as exc:
            self.store.clear_tv_control_url(tv["id"], str(exc))

    def ensure_control_url(self, tv: dict, force: bool = False) -> str:
        if tv.get("control_url") and not force:
            return tv["control_url"]
        bind_ip = get_local_ip_for(tv["ip"])
        info = discover_device(tv["ip"], bind_ip)
        detected = detect_profile(info.get("manufacturer"), info.get("model_name"), info.get("friendly_name"))
        profile = detected if tv["profile"] == "generic_dlna" else tv["profile"]
        self.store.update_tv_discovery(tv["id"], info, profile)
        return str(info["control_url"])

    def push_next(self, tv: dict) -> None:
        tv_id = int(tv["id"])
        lock = self._push_locks.setdefault(tv_id, threading.Lock())
        if not lock.acquire(blocking=False):
            print(f"[worker] skip push tv={tv_id}: push already running", flush=True)
            return
        try:
            now = time.time()
            if now - self._last_push_at.get(tv_id, 0) < config.PUSH_COOLDOWN:
                print(f"[worker] skip push tv={tv_id}: cooldown", flush=True)
                return
            self._last_push_at[tv_id] = now
            self._push_next_locked(tv)
        finally:
            lock.release()

    def _push_next_locked(self, tv: dict) -> None:
        items = self.store.playlist_items(tv["active_playlist_id"])
        if not items:
            return
        profile_key = profile_or_default(tv["profile"])
        playable = self.next_playable_item(tv, items, profile_key)
        if not playable:
            self.store.update_tv_status(tv["id"], True, "WAITING_TRANSCODE")
            return
        index, item = playable

        host = advertise_host_for_tv(tv["ip"])
        media_url = f"http://{host}:{config.HTTP_PORT}/stream/{item['media_id']}?{stream_query(item['media_id'], profile_key)}"
        control_url = self.ensure_control_url(tv)
        print(f"[worker] push tv={tv['id']} media={item['media_id']} index={index} url={media_url}", flush=True)
        self.store.add_event(tv["id"], "push_media", f"Push {item['title']}", media_url)
        try:
            push_video(control_url, media_url, item["title"], "video/mp4")
        except Exception as exc:
            self.store.update_tv_status(tv["id"], False, "ERROR", f"Push failed: {exc}")
            raise

        self.store.set_tv_playback_position(tv["id"], self.advance_index(index, len(items), tv), item["media_id"])
        self.store.update_tv_status(tv["id"], True, "PLAYING")

    def stop_tv(self, tv: dict) -> None:
        control_url = self.ensure_control_url(tv)
        stop_strict(control_url)
        self.store.update_tv_status(tv["id"], True, "STOPPED")
        self.store.add_event(tv["id"], "tv_stop", "Stop sent")

    def next_playable_item(self, tv: dict, items: list[dict], profile_key: str) -> tuple[int, dict] | None:
        start = self.queued_index(tv, items)
        for offset in range(len(items)):
            index = (start + offset) % len(items)
            item = items[index]
            if self.is_item_playable(item, profile_key):
                return index, item
        return None

    def is_item_playable(self, item: dict, profile_key: str) -> bool:
        transcode_row = self.store.get_transcode(item["media_id"], profile_key)
        if not transcode_row:
            self.store.ensure_transcode_job(item["media_id"], profile_key)
            self.store.add_event(None, "skipped_not_ready", f"Queued missing transcode for media {item['media_id']} / {profile_key}")
            return False
        if transcode_row["status"] != "done" or not transcode_row["output_path"]:
            self.store.add_event(None, "skipped_not_ready", f"Skipped media {item['media_id']} / {profile_key}: {transcode_row['status']}")
            return False
        media = self.store.get_media(item["media_id"])
        if not media:
            return False
        expected = output_path(Path(media["original_path"]), profile_key)
        if Path(transcode_row["output_path"]) != expected:
            self.store.requeue_transcode_job(transcode_row["id"])
            return False
        return True

    def queued_index(self, tv: dict, items: list[dict]) -> int:
        index = int(tv.get("current_index") or 0)
        if index >= len(items):
            index = 0

        # Repair old state where current_index pointed at the currently playing item.
        current_media_id = tv.get("current_media_id")
        if current_media_id and len(items) > 1 and items[index]["media_id"] == current_media_id:
            return self.advance_index(index, len(items), tv)
        return index

    def advance_index(self, index: int, total: int, tv: dict) -> int:
        next_index = index + 1
        if next_index >= total:
            return 0 if tv.get("repeat_mode") == "all" else total
        return next_index


def _port_from_url(url: str, default: int) -> int:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.port or default


def advertise_host_for_tv(tv_ip: str) -> str:
    hosts = config.ADVERTISE_HOSTS
    if not hosts:
        return get_local_ip_for(tv_ip)
    if len(hosts) == 1:
        return hosts[0]

    tv_addr = _parse_ip(tv_ip)
    if tv_addr:
        for host in hosts:
            host_addr = _parse_ip(host)
            if not host_addr or host_addr.version != tv_addr.version:
                continue
            prefix = 24 if host_addr.version == 4 else 64
            if tv_addr in ip_network(f"{host_addr}/{prefix}", strict=False):
                return host

    auto_host = get_local_ip_for(tv_ip)
    if auto_host in hosts:
        return auto_host
    return hosts[0]


def _parse_ip(value: str):
    try:
        return ip_address(value)
    except ValueError:
        return None
