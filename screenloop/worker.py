import json
import logging
import threading
import time
from ipaddress import ip_address, ip_network
from pathlib import Path

from . import config, lifecycle, schedule
from .dlna import (
    RESTART_STATES,
    discover_device,
    get_local_ip_for,
    get_transport_state,
    host_ping_reachable,
    push_video,
    set_mute,
    stop_strict,
    tv_is_reachable,
)
from .events import elapsed_seconds, event_details
from .node_hub import hub as node_hub
from .profiles import PROFILES, detect_profile, profile_or_default
from .security import stream_query
from .store import Store
from .transcode import output_path, probe_duration_seconds, transcode

ELAPSED_ADVANCE_STATES = {"PLAYING", "TRANSITIONING", "STOPPED"}
logger = logging.getLogger("screenloop.worker")


class Worker:
    def __init__(self, store: Store):
        self.store = store
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None
        self._transcode_thread: threading.Thread | None = None
        self._push_locks: dict[int, threading.Lock] = {}
        self._last_push_at: dict[int, float] = {}
        self._last_ping_at: dict[int, float] = {}
        self._last_poll_at: dict[int, float] = {}
        # Consecutive polls that found the renderer reset, per TV. A single
        # reading is not enough to call a screen switched off.
        self._reset_streak: dict[int, int] = {}
        self._schedule_settings: dict | None = None
        self._schedule_read_at = 0.0

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
                logger.error("command loop error: %s", exc)
            self._stop.wait(1)

    def run_poll(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_duration_probe()
                self.poll_tvs()
            except Exception as exc:
                logger.error("poll loop error: %s", exc)
            self._stop.wait(config.POLL_LOOP_INTERVAL)

    def run_transcode(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_transcode_job()
            except Exception as exc:
                logger.error("transcode loop error: %s", exc)
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
            media = self.store.get_media(job["media_id"])
            silent = bool(media and media.get("silent"))
            compressed = bool(media and media.get("compressed"))
            out = transcode(Path(job["original_path"]), job["profile"], silent=silent, compressed=compressed)
            self.store.mark_job_done(job["id"], job["media_id"], out)
            self.store.add_event(None, "transcode_done", f"Transcoded media {job['media_id']} for {job['profile']}", str(out))
        except Exception as exc:
            self.store.mark_job_failed(job["id"], job["media_id"], str(exc))
            self.store.add_event(None, "transcode_failed", f"Transcode failed for media {job['media_id']} / {job['profile']}", str(exc))

    def process_tv_command(self) -> None:
        command = self.store.next_pending_command()
        if not command:
            return
        tv = self.store.get_tv(command["tv_id"])
        if tv and tv.get("node_id"):
            self.dispatch_node_command(command, tv)
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

    def dispatch_node_command(self, command: dict, tv: dict) -> None:
        if command["command"] == "stop" and self.command_is_schedule(command) and not self.schedule_stop_needed(tv):
            self.store.mark_command_done(command["id"])
            self.store.add_event(tv["id"], "schedule_stop_skipped", "Skipped stale operating-hours stop")
            return
        node_id = int(tv["node_id"])
        self.store.mark_command_running(command["id"])
        sent = node_hub.send(
            node_id,
            {
                "type": "command",
                "command_id": command["id"],
                "tv_id": tv["id"],
                "action": command["command"],
            },
        )
        if sent:
            if command["command"] == "stop" and not self.command_is_schedule(command):
                self.suspend_after_stop(tv)
            self.store.add_event(tv["id"], "command_started", f"Sent {command['command']} to node {node_id}")
        else:
            self.store.mark_command_failed(command["id"], "Node is offline")
            self.store.add_event(tv["id"], "command_failed", f"{command['command']} failed", "Node is offline")

    def execute_command(self, command: dict) -> None:
        tv = self.store.get_tv(command["tv_id"])
        if not tv:
            raise RuntimeError("TV not found")
        action = command["command"]
        # A person pressing play in the panel outranks both the schedule and a
        # suspension: they can see the screen, we cannot.
        manual = self.command_is_manual(command)
        if manual and action in ("play_next", "restart_playlist"):
            if self.store.resume_tv_playback(tv["id"]):
                self.store.add_event(tv["id"], "playback_resumed", "Playback resumed from the panel")
            self._reset_streak.pop(int(tv["id"]), None)
            tv = self.store.get_tv(tv["id"]) or tv

        if action == "play_next":
            if self.stale_play_next_command(command, tv):
                return
            self.push_next(tv, force=manual)
        elif action == "stop":
            if self.command_is_schedule(command) and not self.schedule_stop_needed(tv):
                self.store.add_event(tv["id"], "schedule_stop_skipped", "Skipped stale operating-hours stop")
                return
            self.stop_tv(tv)
            # Stop has to mean stopped. Without this the screen came back on
            # its own: the poll loop kept seeing STOPPED with media still
            # assigned, and once the clip's duration had elapsed since
            # playback_started_at it queued the next item. `stopped_after_
            # manual_stop` only ever affected the dashboard label, never the
            # decision. A manual play or restart clears the suspension.
            if not self.command_is_schedule(command):
                self.suspend_after_stop(tv)
        elif action == "restart_playlist":
            self.store.set_tv_playback_position(tv["id"], 0, None)
            self.push_next(self.store.get_tv(tv["id"]) or tv, force=manual)
        elif action == "rediscover":
            self.store.clear_tv_control_url(tv["id"], "Rediscover requested")
            self.try_recover_tv(self.store.get_tv(tv["id"]) or tv)
        elif action == "mute":
            self.set_tv_mute(tv, True)
        elif action == "unmute":
            self.set_tv_mute(tv, False)
        elif action == "rebuild_transcode":
            raise RuntimeError("rebuild_transcode is handled by web/store")
        else:
            raise RuntimeError(f"Unknown command: {action}")

    # --- operating hours -------------------------------------------------

    SCHEDULE_CACHE_SECONDS = 5

    def schedule_settings(self) -> dict:
        """The site schedule, re-read occasionally rather than per TV."""
        now = time.time()
        if self._schedule_settings is None or now - self._schedule_read_at >= self.SCHEDULE_CACHE_SECONDS:
            self._schedule_settings = self.store.get_playback_schedule()
            self._schedule_read_at = now
        return self._schedule_settings

    def playback_window(self, tv: dict) -> schedule.Window | None:
        return schedule.resolve_window(tv, self.schedule_settings())

    def may_push(self, tv: dict) -> bool:
        """Whether the worker is allowed to put video on this screen right now.

        The only reason a TV stays off is that nothing sends it `Play`: UPnP
        requires a renderer to leave standby to service that action, and DLNA
        has no power command to undo it with.
        """
        if tv.get("playback_suspended_at") is not None:
            return False
        window = self.playback_window(tv)
        return window is None or window.is_open(schedule.now())

    def apply_schedule(self, tv: dict) -> bool:
        """Enforce the window for one TV. Returns True when pushing is allowed.

        Called from the poll loop before any autoplay decision.
        """
        tv_id = int(tv["id"])
        window = self.playback_window(tv)
        now = schedule.now()

        if window is not None and not window.is_open(now):
            self.park_tv(tv)
            return False

        # A suspension raised before the current window opened has served its
        # purpose: the screen is meant to be showing something again. Derived
        # from the window rather than remembered, so a restart cannot lose it.
        suspended_at = tv.get("playback_suspended_at")
        if suspended_at is not None and window is not None:
            opened_at = window.opened_at(now)
            if opened_at and float(suspended_at) < opened_at.timestamp():
                self.store.resume_tv_playback(tv_id)
                self.store.add_event(
                    tv_id,
                    "schedule_resumed",
                    "Playback resumed with the operating window",
                    f"window opened at {opened_at.isoformat()}",
                )
                self._reset_streak.pop(tv_id, None)
                return True
            return False

        return suspended_at is None

    def park_tv(self, tv: dict) -> None:
        """Stop a screen once when its window closes, then leave it alone."""
        tv_id = int(tv["id"])
        if tv.get("playback_state") in ("STOPPED", "NO_MEDIA_PRESENT", "OFFLINE", "UNKNOWN"):
            return
        if self.store.has_active_command(tv_id, "stop"):
            return
        self.store.add_event(tv_id, "schedule_closed", "Operating window closed, stopping playback")
        # Tagged so the executor knows this blackout is the schedule's doing
        # and leaves no suspension behind: the window gate already refuses to
        # push while it is closed, and a suspension nobody clears is how a
        # screen stays dark after the window reopens.
        self.store.enqueue_command(tv_id, "stop", json.dumps({"source": "schedule"}))

    def suspend_after_stop(self, tv: dict) -> None:
        """Keep a stopped screen stopped until somebody starts it again.

        Only for stops the schedule does not explain. While a window is closed
        `may_push` already refuses, so a scheduled blackout needs no suspension
        -- and leaving one behind is how a screen stays dark after the window
        reopens, if it happened to be offline when the clearing pass ran.
        """
        tv_id = int(tv["id"])
        self._reset_streak.pop(tv_id, None)
        self.store.suspend_tv_playback(tv_id, "stopped_by_operator")
        self.store.add_event(tv_id, "playback_suspended", "Playback stopped, autoplay held until resumed", "source=stop")


    def note_renderer_state(self, tv: dict, state: str) -> None:
        """Suspend a screen whose renderer was reset out from under us.

        Samsung and LG clear the AVTransport instance when they go into
        standby, so a TV somebody switched off with the remote reports
        NO_MEDIA_PRESENT while still answering on the network. The old poll
        loop read that as "nothing is playing, start the playlist", pushed
        `Play`, and switched the panel back on -- every five seconds, all
        night. This is what stops that.
        """
        tv_id = int(tv["id"])
        if state != "NO_MEDIA_PRESENT" or not tv.get("current_media_id"):
            self._reset_streak.pop(tv_id, None)
            return
        if tv.get("playback_suspended_at") is not None:
            return

        streak = self._reset_streak.get(tv_id, 0) + 1
        self._reset_streak[tv_id] = streak
        if streak < max(1, config.MANUAL_OFF_CONFIRMATIONS):
            return

        self._reset_streak.pop(tv_id, None)
        self.store.suspend_tv_playback(tv_id, "renderer_reset")
        self.store.add_event(
            tv_id,
            "playback_suspended",
            "Screen appears to have been switched off, playback suspended",
            f"state={state} for {streak} consecutive polls",
        )

    @staticmethod
    def command_payload(command: dict) -> dict:
        raw = command.get("payload_json")
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def command_is_manual(self, command: dict) -> bool:
        return bool(self.command_payload(command).get("manual"))

    def command_is_schedule(self, command: dict) -> bool:
        return self.command_payload(command).get("source") == "schedule"

    def schedule_stop_needed(self, tv: dict) -> bool:
        """Re-check a queued schedule stop against current persisted settings."""
        window = schedule.resolve_window(tv, self.store.get_playback_schedule())
        return window is not None and not window.is_open(schedule.now())

    def poll_tvs(self) -> None:
        self.store.fail_stale_running_commands()
        for tv in self.store.list_tvs():
            if tv.get("node_id"):
                # Node TVs are polled by their node; status arrives over the websocket.
                continue
            self.poll_tv(tv)

    def poll_tv(self, tv: dict) -> None:
        tv_id = int(tv["id"])
        now = time.time()
        ping_ok = bool(tv.get("ping_reachable"))
        last_ping_at = self._last_ping_at.get(tv_id)
        if last_ping_at is None or now < last_ping_at or now - last_ping_at >= config.PING_POLL:
            ping_ok = host_ping_reachable(tv["ip"])
            self._last_ping_at[tv_id] = now
            self.store.update_tv_health(tv_id, ping_reachable=ping_ok)
        if not ping_ok:
            self.store.mark_tv_unreachable(tv_id)
            return

        full_poll_interval = config.ONLINE_POLL if tv.get("online") and tv.get("control_url") else config.OFFLINE_POLL
        last_poll_at = self._last_poll_at.get(tv_id)
        if last_poll_at is not None and now >= last_poll_at and now - last_poll_at < full_poll_interval:
            return
        self._last_poll_at[tv_id] = now

        try:
            if not tv.get("control_url"):
                self.try_recover_tv(tv)
                tv = self.store.get_tv(tv_id) or tv
                if not tv.get("control_url"):
                    return

            profile = PROFILES[profile_or_default(tv["profile"])]
            probe_port = _port_from_url(tv["control_url"], int(profile.get("probe_port", 9197)))
            dlna_reachable = tv_is_reachable(tv["ip"], probe_port)
            self.store.update_tv_health(tv_id, dlna_reachable=dlna_reachable)
            if not dlna_reachable:
                self.store.clear_tv_control_url(tv_id, f"Probe port {probe_port} is not reachable")
                return

            control_url = self.ensure_control_url(tv)
            state = get_transport_state(control_url)
            self.store.update_tv_status(tv_id, True, self.effective_transport_state(tv, state))
            self.note_renderer_state(tv, state)
            # note_renderer_state may have suspended the TV, and apply_schedule
            # decides on that column.
            tv = self.store.get_tv(tv_id) or tv
            if not self.apply_schedule(tv):
                return
            self.maybe_enqueue_autoplay_next(tv, state)
        except Exception as exc:
            self.store.update_tv_health(tv_id, soap_ready=False, streaming=False)
            self.store.clear_tv_control_url(tv_id, str(exc))

    def maybe_enqueue_autoplay_next(self, tv: dict, state: str) -> bool:
        if not tv.get("autoplay") or not tv.get("active_playlist_id"):
            return False

        if state in RESTART_STATES:
            if state == "STOPPED" and tv.get("current_media_id"):
                return self.maybe_enqueue_elapsed_next(tv, state)
            if self.store.has_active_command(tv["id"], "play_next"):
                return False
            self.store.enqueue_command(tv["id"], "play_next")
            return True

        return self.maybe_enqueue_elapsed_next(tv, state)

    def maybe_enqueue_elapsed_next(self, tv: dict, state: str) -> bool:
        if not self.playback_duration_elapsed(tv, state):
            return False
        if self.store.has_active_command(tv["id"], "play_next"):
            return False

        current_media_id = tv.get("current_media_id")
        duration = self.current_media_duration(tv)
        self.store.add_event(
            tv["id"],
            "duration_elapsed",
            f"Playback duration elapsed for media {current_media_id}",
            f"state={state}; duration={duration}",
        )
        self.store.mark_tv_replay_advance(tv["id"])
        self.store.enqueue_command(tv["id"], "play_next")
        return True

    def playback_duration_elapsed(self, tv: dict, state: str) -> bool:
        if state not in ELAPSED_ADVANCE_STATES:
            return False
        if not tv.get("current_media_id"):
            return False
        started_at = int(tv.get("playback_started_at") or 0)
        if not started_at:
            return False
        duration = self.current_media_duration(tv)
        if duration <= 0:
            threshold = max(config.AUTO_ADVANCE_REPLAY_AFTER, config.AUTO_ADVANCE_UNKNOWN_DURATION_AFTER)
        else:
            threshold = max(config.AUTO_ADVANCE_REPLAY_AFTER, duration + config.AUTO_ADVANCE_END_GRACE)

        last_advance_at = int(tv.get("last_replay_advance_at") or 0)
        if last_advance_at and time.time() - last_advance_at < config.AUTO_ADVANCE_REPLAY_COOLDOWN:
            return False

        return time.time() - started_at >= threshold

    def effective_transport_state(self, tv: dict, state: str) -> str:
        if state != "STOPPED" or not tv.get("current_media_id"):
            return state
        if self.stopped_after_manual_stop(tv):
            return state
        return "PLAYING" if not self.playback_duration_elapsed(tv, state) else state

    def stopped_after_manual_stop(self, tv: dict) -> bool:
        if tv.get("last_command") != "stop" or tv.get("last_command_status") != "done":
            return False
        finished_at = int(tv.get("last_command_finished_at") or 0)
        started_at = int(tv.get("playback_started_at") or 0)
        return bool(finished_at and started_at and finished_at >= started_at)

    def current_media_duration(self, tv: dict) -> int:
        duration = tv.get("current_media_duration_seconds")
        if duration is None and tv.get("current_media_id"):
            media = self.store.get_media(tv["current_media_id"])
            duration = media.get("duration_seconds") if media else None
        try:
            return int(float(duration or 0))
        except (TypeError, ValueError):
            return 0

    def try_recover_tv(self, tv: dict) -> None:
        try:
            self.ensure_control_url(tv, force=True)
            fresh_tv = self.store.get_tv(tv["id"]) or tv
            self.store.add_event(tv["id"], "tv_found", f"TV found: {fresh_tv.get('control_url')}")
            self.store.update_tv_health(tv["id"], dlna_reachable=True, soap_ready=True)
            self.store.update_tv_status(tv["id"], True, "ONLINE")
            # Rediscovery used to restart the playlist unconditionally, which
            # turned every reappearance of a screen -- including one waking
            # briefly from standby -- back into a push.
            if fresh_tv.get("autoplay") and fresh_tv.get("active_playlist_id") and self.may_push(fresh_tv):
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

    def push_next(self, tv: dict, force: bool = False) -> None:
        tv_id = int(tv["id"])
        # The single choke point every push goes through, so the operating
        # window is enforced here rather than at each of the places that queue
        # a play_next. `force` is set for commands a person pressed.
        if not force and not self.may_push(tv):
            reason = "suspended" if tv.get("playback_suspended_at") is not None else "outside the operating window"
            logger.info("skip push tv=%s: %s", tv_id, reason)
            self.store.add_event(tv_id, "push_skipped", f"Push skipped: {reason}")
            return
        lock = self._push_locks.setdefault(tv_id, threading.Lock())
        if not lock.acquire(blocking=False):
            logger.info("skip push tv=%s: push already running", tv_id)
            return
        try:
            now = time.time()
            if now - self._last_push_at.get(tv_id, 0) < config.PUSH_COOLDOWN:
                logger.info("skip push tv=%s: cooldown", tv_id)
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

        profile = PROFILES[profile_key]
        mime_type = str(profile.get("mime_type") or "video/mp4")
        protocol_info = profile.get("dlna_protocol_info")
        media_url = stream_url_for_tv(tv["ip"], item["media_id"], profile_key)
        preload = self.next_preload_item(tv, items, index, profile_key)
        next_item = preload[1] if preload else None
        next_media_url = stream_url_for_tv(tv["ip"], next_item["media_id"], profile_key) if next_item else None
        control_url = self.ensure_control_url(tv)
        logger.info("push tv=%s media=%s index=%s url=%s", tv["id"], item["media_id"], index, media_url.split("?", 1)[0])
        push_started_at = time.time()
        push_event_id = self.store.add_event(
            tv["id"],
            "push_media",
            f"Push {item['title']}",
            event_details(
                media_id=item["media_id"],
                index=index,
                next_media_id=next_item["media_id"] if next_item else None,
                url=media_url.split("?", 1)[0],
            ),
        )
        try:
            next_preloaded = push_video(
                control_url,
                media_url,
                item["title"],
                mime_type,
                protocol_info=protocol_info,
                next_media_url=next_media_url,
                next_file_name=next_item["title"] if next_item else "",
                next_mime_type=mime_type,
                next_protocol_info=protocol_info,
            )
        except Exception as exc:
            if self.tv_started_requested_media(tv["id"], item["media_id"]):
                self.store.add_event(
                    tv["id"],
                    "push_timeout_ignored",
                    f"TV started stream for {item['title']} despite control error",
                    event_details(
                        media_id=item["media_id"],
                        push_event_id=push_event_id,
                        push_elapsed_s=elapsed_seconds(push_started_at, time.time()),
                        error=exc,
                    ),
                )
                self.reapply_mute_quiet(self.store.get_tv(tv["id"]) or tv)
                return
            self.store.update_tv_status(tv["id"], False, "ERROR", f"Push failed: {exc}")
            raise

        if next_preloaded and next_item:
            self.store.add_event(
                tv["id"],
                "preload_next_uri",
                f"Preloaded next media {next_item['media_id']}",
                event_details(
                    source="push",
                    media_id=item["media_id"],
                    target_media_id=next_item["media_id"],
                    push_event_id=push_event_id,
                    push_elapsed_s=elapsed_seconds(push_started_at, time.time()),
                ),
            )
        self.store.set_tv_playback_position(tv["id"], self.advance_index(index, len(items), tv), item["media_id"])
        self.store.update_tv_status(tv["id"], True, "PLAYING")
        self.reapply_mute_quiet(self.store.get_tv(tv["id"]) or tv)

    def stop_tv(self, tv: dict) -> None:
        control_url = self.ensure_control_url(tv)
        stop_strict(control_url)
        self.store.update_tv_status(tv["id"], True, "STOPPED")
        self.store.add_event(tv["id"], "tv_stop", "Stop sent")

    def set_tv_mute(self, tv: dict, muted: bool) -> None:
        rc_url = self.ensure_rendering_control_url(tv)
        set_mute(rc_url, muted)
        self.store.set_tv_muted(tv["id"], muted)
        label = "tv_muted" if muted else "tv_unmuted"
        self.store.add_event(tv["id"], label, "Mute on" if muted else "Mute off")

    def ensure_rendering_control_url(self, tv: dict) -> str:
        rc_url = tv.get("rendering_control_url")
        if rc_url:
            return rc_url
        bind_ip = get_local_ip_for(tv["ip"])
        info = discover_device(tv["ip"], bind_ip)
        rc_url = info.get("rendering_control_url")
        if not rc_url:
            raise RuntimeError("RenderingControl service not advertised by this TV")
        self.store.set_tv_rendering_control_url(tv["id"], rc_url)
        return rc_url

    def reapply_mute_quiet(self, tv: dict) -> None:
        if not tv.get("muted"):
            return
        try:
            rc_url = self.ensure_rendering_control_url(tv)
            set_mute(rc_url, True)
        except Exception as exc:
            logger.warning("reapply mute failed tv=%s: %s", tv.get("id"), exc)

    def next_playable_item(self, tv: dict, items: list[dict], profile_key: str) -> tuple[int, dict] | None:
        start = self.queued_index(tv, items)
        for offset in range(len(items)):
            index = (start + offset) % len(items)
            item = items[index]
            if self.is_item_playable(item, profile_key):
                return index, item
        return None

    def next_preload_item(self, tv: dict, items: list[dict], current_index: int, profile_key: str) -> tuple[int, dict] | None:
        if len(items) < 2:
            return None
        start = self.advance_index(current_index, len(items), tv)
        if start >= len(items):
            return None
        for offset in range(len(items) - 1):
            index = (start + offset) % len(items)
            if index == current_index:
                continue
            item = items[index]
            if self.is_item_playable(item, profile_key):
                return index, item
        return None

    def tv_started_requested_media(self, tv_id: int, media_id: int) -> bool:
        tv = self.store.get_tv(tv_id)
        if not tv or tv.get("current_media_id") != media_id:
            return False
        state = str(tv.get("playback_state") or "")
        return bool(tv.get("streaming")) or state in {"PLAYING", "TRANSITIONING"}

    def stale_play_next_command(self, command: dict, tv: dict) -> bool:
        created_at = int(command.get("created_at") or 0)
        playback_started_at = int(tv.get("playback_started_at") or 0)
        if not created_at or not playback_started_at or not tv.get("current_media_id"):
            return False
        if playback_started_at <= created_at:
            return False
        self.store.add_event(
            tv["id"],
            "stale_play_next_skipped",
            "Skipped stale play_next after stream sync",
            f"command_created_at={created_at}; playback_started_at={playback_started_at}",
        )
        return True

    def is_item_playable(self, item: dict, profile_key: str) -> bool:
        # The lifecycle gate. `push_next` decides whether this *screen* may be
        # pushed to; this is the one place that decides whether a *clip* may
        # go out, and both the item being pushed and the one preloaded behind
        # it come through here. A draft nobody approved, an archived clip, and
        # one past its expiry all stop here rather than at any caller.
        media = self.store.get_media(item["media_id"])
        if not media:
            return False
        if not lifecycle.playable(media):
            self.store.add_event(
                None,
                "skipped_not_published",
                f"Skipped media {item['media_id']}: {lifecycle.effective_state(media)}",
            )
            return False
        transcode_row = self.store.get_transcode(item["media_id"], profile_key)
        if not transcode_row:
            self.store.ensure_transcode_job(item["media_id"], profile_key)
            self.store.add_event(None, "skipped_not_ready", f"Queued missing transcode for media {item['media_id']} / {profile_key}")
            return False
        if transcode_row["status"] != "done" or not transcode_row["output_path"]:
            self.store.add_event(None, "skipped_not_ready", f"Skipped media {item['media_id']} / {profile_key}: {transcode_row['status']}")
            return False
        expected = output_path(
            Path(media["original_path"]),
            profile_key,
            silent=bool(media.get("silent")),
            compressed=bool(media.get("compressed")),
        )
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


def stream_url_for_tv(tv_ip: str, media_id: int, profile_key: str) -> str:
    query = stream_query(media_id, profile_key, tv_ip)
    public_url = _clean_url(config.PUBLIC_URL).rstrip("/")
    if public_url:
        return f"{public_url}/stream/{media_id}?{query}"
    host = _clean_url(advertise_host_for_tv(tv_ip))
    return f"http://{host}:{config.HTTP_PORT}/stream/{media_id}?{query}"


def _clean_url(value: str) -> str:
    return (value or "").strip().strip("\"'").replace("'", "").replace('"', "")


def _parse_ip(value: str):
    try:
        return ip_address(value)
    except ValueError:
        return None
