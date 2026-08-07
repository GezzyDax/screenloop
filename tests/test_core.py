import sqlite3
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from screenloop import config as config_module
from screenloop import profiles as profiles_module
from screenloop import transcode as transcode_module
from screenloop import worker as worker_module
from screenloop.dlna import make_didl, parse_ssdp_response
from screenloop.profiles import (
    PROFILES,
    TemplateError,
    detect_profile,
    parse_template,
    profile_or_default,
    reload_profiles,
    validate_template,
)
from screenloop.security import create_csrf_token, create_stream_token, verify_csrf_token, verify_stream_token
from screenloop.store import Store
from screenloop.transcode import compressed_profile, output_path, video_filter
from screenloop.worker import Worker, advertise_host_for_tv, stream_url_for_tv


class CoreTests(unittest.TestCase):
    def test_frontend_proxy_limits_upload_body_size(self):
        root = Path(__file__).resolve().parents[1]
        nginx_template = (root / "frontend" / "nginx.conf.template").read_text()

        self.assertIn("client_max_body_size ${SCREENLOOP_MAX_UPLOAD_BYTES};", nginx_template)
        self.assertNotIn("client_max_body_size 0;", nginx_template)

    def test_parse_ssdp_response_lowercases_headers(self):
        data = (
            b"HTTP/1.1 200 OK\r\n"
            b"LOCATION: http://192.168.1.20:9197/rootDesc.xml\r\n"
            b"ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n"
        )

        headers = parse_ssdp_response(data)

        self.assertEqual(headers["location"], "http://192.168.1.20:9197/rootDesc.xml")
        self.assertEqual(headers["st"], "urn:schemas-upnp-org:device:MediaRenderer:1")

    def test_didl_escapes_title_and_url(self):
        didl = make_didl("http://host/video?a=1&b=2", "A&B <test>", "video/mp4")

        self.assertIn("A&amp;B &lt;test&gt;", didl)
        self.assertIn("http://host/video?a=1&amp;b=2", didl)
        self.assertIn("video/mp4", didl)

    def test_didl_accepts_profile_protocol_info(self):
        protocol_info = "http-get:*:video/mp4:DLNA.ORG_PN=AVC_MP4_MP_HD_1080i_AAC;DLNA.ORG_OP=01"

        didl = make_didl("http://host/video.mp4", "video", "video/mp4", protocol_info=protocol_info)

        self.assertIn("DLNA.ORG_PN=AVC_MP4_MP_HD_1080i_AAC", didl)
        self.assertIn("DLNA.ORG_OP=01", didl)

    def test_detect_profile_prefers_known_vendor(self):
        self.assertEqual(detect_profile("LG Electronics", "webOS TV"), "lg_webos")
        self.assertEqual(detect_profile("Samsung", "Tizen"), "samsung_tizen")
        self.assertEqual(detect_profile("Samsung Electronics", "UE32F6400"), "samsung_legacy")
        self.assertEqual(detect_profile("Unknown", "MediaRenderer"), "generic_dlna")

    def test_profile_fallback(self):
        self.assertEqual(profile_or_default("lg_webos"), "lg_webos")
        self.assertEqual(profile_or_default("missing"), "generic_dlna")
        self.assertEqual(profile_or_default(None), "generic_dlna")

    def test_store_keeps_transcode_jobs_per_profile(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.sqlite3"
            source = Path(tmp) / "video.mkv"
            source.write_bytes(b"video")
            store = Store(db)

            media_id = store.add_media("video", source, "video.mkv", source.stat().st_size, "abc")
            store.ensure_transcode_job(media_id, "generic_dlna")
            store.ensure_transcode_job(media_id, "lg_webos")

            generic = store.get_transcode(media_id, "generic_dlna")
            lg = store.get_transcode(media_id, "lg_webos")

            self.assertIsNotNone(generic)
            self.assertIsNotNone(lg)
            self.assertNotEqual(generic["id"], lg["id"])

    def test_store_tracks_tv_by_ip_and_playback_start(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            tv_id = store.add_tv("TV", "192.168.1.50", "generic_dlna")
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            media_id = store.add_media("video", source, "video.mp4", source.stat().st_size, "abc")
            store.set_tv_playback_position(tv_id, 1, media_id)

            tv = store.get_tv_by_ip("192.168.1.50")

            self.assertEqual(tv["current_index"], 1)
            self.assertEqual(tv["current_media_id"], media_id)
            self.assertIsNotNone(tv["playback_started_at"])
            self.assertIsNone(tv["last_replay_advance_at"])

    def test_store_tv_list_includes_playback_diagnostics(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            first_media = store.add_media("first", source, "first.mp4", source.stat().st_size, "a", duration_seconds=30)
            second_media = store.add_media("second", source, "second.mp4", source.stat().st_size, "b", duration_seconds=40)
            playlist_id = store.create_playlist("playlist")
            store.add_playlist_item(playlist_id, first_media)
            store.add_playlist_item(playlist_id, second_media)
            tv_id = store.add_tv("TV", "192.168.1.50", "generic_dlna")
            store.update_tv_config(tv_id, "TV", "192.168.1.50", "generic_dlna", playlist_id, True)
            store.set_tv_playback_position(tv_id, 1, first_media)
            store.add_event(tv_id, "push_media", "Push first", "http://example/stream/1?token=secret")

            tv = store.list_tvs()[0]

            self.assertEqual(tv["current_media_duration_seconds"], 30)
            self.assertEqual(tv["next_media_id"], second_media)
            self.assertEqual(tv["next_media_title"], "second")
            self.assertEqual(tv["last_stream_event_type"], "push_media")
            self.assertIn("/stream/1", tv["last_stream_event_details"])

    def test_store_resets_playback_when_playlist_changes(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            media_id = store.add_media("video", source, "video.mp4", source.stat().st_size, "abc")
            first_playlist = store.create_playlist("first")
            second_playlist = store.create_playlist("second")
            tv_id = store.add_tv("TV", "192.168.1.51", "generic_dlna")

            store.update_tv_config(tv_id, "TV", "192.168.1.51", "generic_dlna", first_playlist, True)
            store.set_tv_playback_position(tv_id, 2, media_id)
            store.update_tv_config(tv_id, "TV", "192.168.1.51", "generic_dlna", second_playlist, True)
            tv = store.get_tv(tv_id)

            self.assertEqual(tv["active_playlist_id"], second_playlist)
            self.assertEqual(tv["current_index"], 0)
            self.assertIsNone(tv["current_media_id"])
            self.assertIsNone(tv["playback_started_at"])

    def test_store_can_clear_dead_control_url(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            tv_id = store.add_tv("TV", "192.168.1.52", "generic_dlna")
            store.set_tv_control_url(tv_id, "http://192.168.1.52:123/control.xml")

            store.clear_tv_control_url(tv_id, "dead")
            tv = store.get_tv(tv_id)

            self.assertIsNone(tv["control_url"])
            self.assertEqual(tv["online"], 0)
            self.assertEqual(tv["playback_state"], "OFFLINE")
            self.assertEqual(tv["last_error"], "dead")

    def test_store_marks_unreachable_tv_offline_without_forgetting_control_url(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            tv_id = store.add_tv("TV", "192.168.1.52", "generic_dlna")
            control_url = "http://192.168.1.52:123/control.xml"
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            media_id = store.add_media("video", source, "video.mp4", source.stat().st_size, "abc")
            store.set_tv_control_url(tv_id, control_url)
            store.mark_tv_stream_playback(tv_id, 0, media_id, reset_started=True)

            store.mark_tv_unreachable(tv_id)
            tv = store.get_tv(tv_id)

            self.assertEqual(tv["online"], 0)
            self.assertEqual(tv["ping_reachable"], 0)
            self.assertEqual(tv["dlna_reachable"], 0)
            self.assertEqual(tv["soap_ready"], 0)
            self.assertEqual(tv["streaming"], 0)
            self.assertEqual(tv["playback_state"], "OFFLINE")
            self.assertEqual(tv["control_url"], control_url)

    def test_store_commands_are_sequential_and_deduped(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            tv_id = store.add_tv("TV", "192.168.1.53", "generic_dlna")

            first = store.enqueue_command(tv_id, "play_next")
            second = store.enqueue_command(tv_id, "play_next")
            stop_id = store.enqueue_command(tv_id, "stop")

            self.assertEqual(first, second)
            command = store.next_pending_command()
            self.assertEqual(command["id"], first)
            store.mark_command_running(first)
            self.assertIsNone(store.next_pending_command())
            store.mark_command_done(first)
            self.assertEqual(store.next_pending_command()["id"], stop_id)

    def test_store_fails_running_commands_after_restart(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            tv_id = store.add_tv("TV", "192.168.1.54", "generic_dlna")
            command_id = store.enqueue_command(tv_id, "play_next")
            store.mark_command_running(command_id)

            self.assertEqual(store.fail_running_commands("restart"), 1)
            command = store.recent_commands_for_tv(tv_id, 1)[0]

            self.assertEqual(command["status"], "failed")
            self.assertEqual(command["error"], "restart")
            event = store.list_events(tv_id, "command_failed", 1)[0]
            self.assertIn("play_next failed", event["message"])

    def test_store_event_retention_keeps_last_1000(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            for index in range(1005):
                store.add_event(None, "test", f"event {index}")

            events = store.list_events(limit=1100)

            self.assertEqual(len(events), 1000)
            self.assertEqual(events[0]["message"], "event 1004")
            self.assertEqual(events[-1]["message"], "event 5")

    def test_store_event_retention_preserves_security_audit(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            store.add_event(None, "login_failed", "audit login")
            store.add_event(None, "security_denied", "audit denied")
            store.add_event(None, "user_created", "audit user")
            for index in range(1005):
                store.add_event(None, "test", f"event {index}")

            security_events = [
                event
                for event in store.list_events(limit=6100)
                if event["event_type"] in {"login_failed", "security_denied", "user_created"}
            ]

            self.assertEqual(len(security_events), 3)

    def test_store_rebuild_transcode_job_resets_state(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            store = Store(Path(tmp) / "test.sqlite3")
            media_id = store.add_media("video", source, "video.mp4", source.stat().st_size, "abc")
            store.ensure_transcode_job(media_id, "generic_dlna")
            job = store.get_transcode(media_id, "generic_dlna")
            store.mark_job_failed(job["id"], media_id, "bad")

            store.rebuild_transcode_job(job["id"])
            rebuilt = store.get_transcode(media_id, "generic_dlna")

            self.assertEqual(rebuilt["status"], "pending")
            self.assertEqual(rebuilt["attempts"], 0)
            self.assertIsNone(rebuilt["output_path"])
            self.assertIsNone(rebuilt["error"])

    def test_store_can_reorder_and_compact_playlist_items(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            media_ids = [
                store.add_media(f"video-{index}", source, f"video-{index}.mp4", source.stat().st_size, str(index))
                for index in range(3)
            ]
            playlist_id = store.create_playlist("playlist")
            for media_id in media_ids:
                store.add_playlist_item(playlist_id, media_id)

            second_item = store.playlist_items(playlist_id)[1]
            store.move_playlist_item(second_item["id"], "up")
            items = store.playlist_items(playlist_id)

            self.assertEqual([item["media_id"] for item in items], [media_ids[1], media_ids[0], media_ids[2]])
            store.remove_playlist_item(items[1]["id"])
            self.assertEqual([item["position"] for item in store.playlist_items(playlist_id)], [0, 1])

    def test_output_path_differs_by_audio_and_compression_flags(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")

            audible = output_path(source, "generic_dlna", silent=False)
            silent = output_path(source, "generic_dlna", silent=True)
            compressed = output_path(source, "generic_dlna", compressed=True)

            self.assertNotEqual(audible, silent)
            self.assertNotEqual(audible, compressed)
            self.assertIn(".silent.", silent.name)
            self.assertIn(".compressed.", compressed.name)
            self.assertNotIn(".silent.", audible.name)

    def test_compressed_profile_targets_smaller_720p_output(self):
        profile = compressed_profile(PROFILES["generic_dlna"]["ffmpeg"], compressed=True)

        self.assertEqual(profile["target_width"], 1280)
        self.assertEqual(profile["target_height"], 720)
        self.assertGreaterEqual(profile["crf"], 30)
        self.assertEqual(profile["maxrate"], "3000k")
        self.assertEqual(profile["bufsize"], "6000k")
        self.assertEqual(profile["audio_bitrate"], "96k")
        self.assertEqual(profile["preset"], "medium")

    def test_store_media_flags_requeue_transcode_jobs(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            store = Store(Path(tmp) / "test.sqlite3")
            media_id = store.add_media("video", source, "video.mp4", source.stat().st_size, "abc")
            store.ensure_transcode_job(media_id, "generic_dlna")
            job = store.get_transcode(media_id, "generic_dlna")
            store.mark_job_done(job["id"], media_id, source)
            self.assertEqual(store.get_transcode(media_id, "generic_dlna")["status"], "done")

            store.set_media_silent(media_id, True)
            store.set_media_compressed(media_id, True)
            store.requeue_transcode_jobs_for_media(media_id)

            refreshed = store.get_transcode(media_id, "generic_dlna")
            media = store.get_media(media_id)
            self.assertEqual(media["silent"], 1)
            self.assertEqual(media["compressed"], 1)
            self.assertEqual(refreshed["status"], "pending")
            self.assertIsNone(refreshed["output_path"])
            self.assertEqual(media["status"], "uploaded")

    def test_store_persists_muted_flag_and_rendering_control_url(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            tv_id = store.add_tv("TV", "192.168.1.60", "generic_dlna")

            store.set_tv_rendering_control_url(tv_id, "http://192.168.1.60:9197/rc")
            store.set_tv_muted(tv_id, True)
            tv = store.get_tv(tv_id)

            self.assertEqual(tv["rendering_control_url"], "http://192.168.1.60:9197/rc")
            self.assertEqual(tv["muted"], 1)

            store.set_tv_muted(tv_id, False)
            self.assertEqual(store.get_tv(tv_id)["muted"], 0)

    def test_store_tracks_split_tv_health(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            tv_id = store.add_tv("TV", "192.168.1.54", "generic_dlna")

            store.update_tv_health(tv_id, ping_reachable=True, dlna_reachable=True)
            store.update_tv_status(tv_id, True, "PLAYING")
            tv = store.get_tv(tv_id)

            self.assertEqual(tv["ping_reachable"], 1)
            self.assertEqual(tv["dlna_reachable"], 1)
            self.assertEqual(tv["soap_ready"], 1)
            self.assertEqual(tv["streaming"], 1)

    def test_store_bootstrap_users_and_sessions(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")

            user_id = store.ensure_bootstrap_admin("admin", "long-password-value")
            duplicate = store.ensure_bootstrap_admin("other", "long-password-value")
            user = store.authenticate_user("admin", "long-password-value")
            token = store.create_session(user_id, "192.0.2.15", "test-agent")
            session_user = store.get_session_user(token)

            self.assertIsNotNone(user_id)
            self.assertIsNone(duplicate)
            self.assertEqual(user["role"], "admin")
            self.assertEqual(session_user["username"], "admin")
            self.assertIsNone(store.authenticate_user("admin", "wrong-password"))

    def test_store_roles_and_password_change_invalidate_sessions(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            user_id = store.create_user("viewer", "long-password-value", "viewer")
            token = store.create_session(user_id, "192.0.2.15", "test-agent")

            store.update_user(user_id, "operator", False)
            updated = store.get_user(user_id)
            store.set_user_password(user_id, "new-long-password")

            self.assertEqual(updated["role"], "operator")
            self.assertIsNone(store.get_session_user(token))
            self.assertIsNotNone(store.authenticate_user("viewer", "new-long-password"))

    def test_worker_queue_advances_after_push(self):
        worker = Worker.__new__(Worker)
        items = [{"media_id": 3}, {"media_id": 2}, {"media_id": 1}]

        self.assertEqual(worker.queued_index({"current_index": 0, "current_media_id": None, "repeat_mode": "all"}, items), 0)
        self.assertEqual(worker.advance_index(0, len(items), {"repeat_mode": "all"}), 1)
        self.assertEqual(worker.advance_index(1, len(items), {"repeat_mode": "all"}), 2)
        self.assertEqual(worker.advance_index(2, len(items), {"repeat_mode": "all"}), 0)

    def test_worker_repairs_index_pointing_at_current_media(self):
        worker = Worker.__new__(Worker)
        items = [{"media_id": 3}, {"media_id": 2}, {"media_id": 1}]

        self.assertEqual(worker.queued_index({"current_index": 2, "current_media_id": 1, "repeat_mode": "all"}, items), 0)

    def test_worker_queues_next_when_lg_keeps_playing_after_duration(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            first_media = store.add_media("first", source, "first.mp4", source.stat().st_size, "a", duration_seconds=10)
            second_media = store.add_media("second", source, "second.mp4", source.stat().st_size, "b", duration_seconds=20)
            playlist_id = store.create_playlist("playlist")
            store.add_playlist_item(playlist_id, first_media)
            store.add_playlist_item(playlist_id, second_media)
            tv_id = store.add_tv("TV", "192.168.1.55", "lg_webos")
            store.update_tv_config(tv_id, "TV", "192.168.1.55", "lg_webos", playlist_id, True)
            store.set_tv_playback_position(tv_id, 1, first_media)
            tv = store.list_tvs()[0]
            tv["playback_started_at"] = int(time.time()) - 20
            worker = Worker(store)

            self.assertTrue(worker.maybe_enqueue_autoplay_next(tv, "PLAYING"))

            command = store.next_pending_command()
            self.assertIsNotNone(command)
            self.assertEqual(command["command"], "play_next")
            event = store.list_events(tv_id, "duration_elapsed", 1)[0]
            self.assertIn(str(first_media), event["message"])

    def test_worker_does_not_duration_advance_before_threshold_or_when_paused(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            media_id = store.add_media("video", source, "video.mp4", source.stat().st_size, "a", duration_seconds=30)
            playlist_id = store.create_playlist("playlist")
            store.add_playlist_item(playlist_id, media_id)
            tv_id = store.add_tv("TV", "192.168.1.56", "lg_webos")
            store.update_tv_config(tv_id, "TV", "192.168.1.56", "lg_webos", playlist_id, True)
            store.set_tv_playback_position(tv_id, 0, media_id)
            tv = store.list_tvs()[0]
            worker = Worker(store)

            tv["playback_started_at"] = int(time.time()) - 10
            self.assertFalse(worker.maybe_enqueue_autoplay_next(tv, "PLAYING"))

            tv["playback_started_at"] = int(time.time()) - 60
            self.assertFalse(worker.maybe_enqueue_autoplay_next(tv, "PAUSED_PLAYBACK"))
            self.assertIsNone(store.next_pending_command())

    def test_worker_ignores_early_lg_stopped_state_with_active_media(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            media_id = store.add_media("video", source, "video.mp4", source.stat().st_size, "a", duration_seconds=120)
            playlist_id = store.create_playlist("playlist")
            store.add_playlist_item(playlist_id, media_id)
            tv_id = store.add_tv("TV", "192.168.1.57", "lg_webos")
            store.update_tv_config(tv_id, "TV", "192.168.1.57", "lg_webos", playlist_id, True)
            store.set_tv_playback_position(tv_id, 0, media_id)
            tv = store.list_tvs()[0]
            tv["playback_started_at"] = int(time.time()) - 6
            worker = Worker(store)

            self.assertFalse(worker.maybe_enqueue_autoplay_next(tv, "STOPPED"))
            self.assertEqual(worker.effective_transport_state(tv, "STOPPED"), "PLAYING")
            self.assertIsNone(store.next_pending_command())

    def test_worker_advances_lg_stopped_state_after_duration(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            first_media = store.add_media("first", source, "first.mp4", source.stat().st_size, "a", duration_seconds=10)
            second_media = store.add_media("second", source, "second.mp4", source.stat().st_size, "b", duration_seconds=20)
            playlist_id = store.create_playlist("playlist")
            store.add_playlist_item(playlist_id, first_media)
            store.add_playlist_item(playlist_id, second_media)
            tv_id = store.add_tv("TV", "192.168.1.59", "lg_webos")
            store.update_tv_config(tv_id, "TV", "192.168.1.59", "lg_webos", playlist_id, True)
            store.set_tv_playback_position(tv_id, 1, first_media)
            tv = store.list_tvs()[0]
            tv["playback_started_at"] = int(time.time()) - 20
            worker = Worker(store)

            self.assertTrue(worker.maybe_enqueue_autoplay_next(tv, "STOPPED"))
            command = store.next_pending_command()
            self.assertIsNotNone(command)
            self.assertEqual(command["command"], "play_next")
            event = store.list_events(tv_id, "duration_elapsed", 1)[0]
            self.assertIn("state=STOPPED", event["details"])

    def test_worker_keeps_manual_stop_visible(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            media_id = store.add_media("video", source, "video.mp4", source.stat().st_size, "a", duration_seconds=120)
            playlist_id = store.create_playlist("playlist")
            store.add_playlist_item(playlist_id, media_id)
            tv_id = store.add_tv("TV", "192.168.1.60", "lg_webos")
            store.update_tv_config(tv_id, "TV", "192.168.1.60", "lg_webos", playlist_id, True)
            store.set_tv_playback_position(tv_id, 0, media_id)
            stop_id = store.enqueue_command(tv_id, "stop")
            store.mark_command_running(stop_id)
            store.mark_command_done(stop_id)
            tv = store.list_tvs()[0]
            worker = Worker(store)

            self.assertEqual(worker.effective_transport_state(tv, "STOPPED"), "STOPPED")

    def test_worker_marks_tv_offline_when_ping_fails(self):
        with TemporaryDirectory() as tmp:
            original_ping = worker_module.host_ping_reachable
            try:
                worker_module.host_ping_reachable = lambda *_args, **_kwargs: False
                store = Store(Path(tmp) / "test.sqlite3")
                tv_id = store.add_tv("TV", "192.168.1.61", "lg_webos")
                source = Path(tmp) / "video.mp4"
                source.write_bytes(b"video")
                media_id = store.add_media("video", source, "video.mp4", source.stat().st_size, "abc")
                store.set_tv_control_url(tv_id, "http://192.168.1.61:9197/AVTransport/control")
                store.mark_tv_stream_playback(tv_id, 0, media_id, reset_started=True)
                worker = Worker(store)

                worker.poll_tv(store.get_tv(tv_id))
                tv = store.get_tv(tv_id)

                self.assertEqual(tv["online"], 0)
                self.assertEqual(tv["ping_reachable"], 0)
                self.assertEqual(tv["dlna_reachable"], 0)
                self.assertEqual(tv["soap_ready"], 0)
                self.assertEqual(tv["streaming"], 0)
                self.assertEqual(tv["playback_state"], "OFFLINE")
            finally:
                worker_module.host_ping_reachable = original_ping

    def test_worker_skips_stale_play_next_after_stream_sync(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")
            media_id = store.add_media("video", source, "video.mp4", source.stat().st_size, "a", duration_seconds=30)
            tv_id = store.add_tv("TV", "192.168.1.58", "lg_webos")
            store.set_tv_playback_position(tv_id, 0, media_id)
            tv = store.get_tv(tv_id)
            worker = Worker(store)

            self.assertTrue(worker.stale_play_next_command({"created_at": tv["playback_started_at"] - 1}, tv))
            self.assertFalse(worker.stale_play_next_command({"created_at": tv["playback_started_at"] + 1}, tv))
            event = store.list_events(tv_id, "stale_play_next_skipped", 1)[0]
            self.assertIn("stream sync", event["message"])

    def test_worker_accepts_stream_start_after_lg_control_timeout(self):
        with TemporaryDirectory() as tmp:
            original_transcode_dir = transcode_module.TRANSCODE_DIR
            original_public_url = worker_module.config.PUBLIC_URL
            original_push_video = worker_module.push_video
            transcode_module.TRANSCODE_DIR = Path(tmp) / "transcoded"
            worker_module.config.PUBLIC_URL = "http://screenloop.test"
            try:
                store = Store(Path(tmp) / "test.sqlite3")
                source = Path(tmp) / "video.mp4"
                source.write_bytes(b"video")
                first_media = store.add_media("first", source, "first.mp4", source.stat().st_size, "a", duration_seconds=10)
                second_media = store.add_media("second", source, "second.mp4", source.stat().st_size, "b", duration_seconds=20)
                for media_id in (first_media, second_media):
                    store.ensure_transcode_job(media_id, "lg_webos")
                    job = store.get_transcode(media_id, "lg_webos")
                    ready_path = output_path(source, "lg_webos")
                    ready_path.parent.mkdir(parents=True, exist_ok=True)
                    ready_path.write_bytes(b"ready")
                    store.mark_job_done(job["id"], media_id, ready_path)
                playlist_id = store.create_playlist("playlist")
                store.add_playlist_item(playlist_id, first_media)
                store.add_playlist_item(playlist_id, second_media)
                tv_id = store.add_tv("TV", "192.168.1.57", "lg_webos")
                store.update_tv_config(
                    tv_id,
                    "TV",
                    "192.168.1.57",
                    "lg_webos",
                    playlist_id,
                    True,
                    "http://192.168.1.57:9197/AVTransport/control",
                )

                def fake_push_video(*args, **kwargs):
                    store.mark_tv_stream_playback(tv_id, 1, first_media, reset_started=True)
                    raise TimeoutError("timed out")

                worker_module.push_video = fake_push_video
                worker = Worker(store)
                worker._push_next_locked(store.get_tv(tv_id))

                tv = store.get_tv(tv_id)
                self.assertEqual(tv["current_media_id"], first_media)
                self.assertEqual(tv["current_index"], 1)
                self.assertEqual(tv["playback_state"], "PLAYING")
                self.assertIsNone(tv["last_error"])
                event = store.list_events(tv_id, "push_timeout_ignored", 1)[0]
                self.assertIn("despite control error", event["message"])
            finally:
                transcode_module.TRANSCODE_DIR = original_transcode_dir
                worker_module.config.PUBLIC_URL = original_public_url
                worker_module.push_video = original_push_video

    def test_worker_skips_unready_items(self):
        worker = Worker.__new__(Worker)
        ready = {2}
        worker.is_item_playable = lambda item, profile: item["media_id"] in ready
        items = [{"media_id": 1}, {"media_id": 2}, {"media_id": 3}]

        index, item = worker.next_playable_item(
            {"current_index": 0, "current_media_id": None, "repeat_mode": "all"},
            items,
            "generic_dlna",
        )

        self.assertEqual(index, 1)
        self.assertEqual(item["media_id"], 2)

    def test_advertise_host_selects_same_subnet_candidate(self):
        original_hosts = worker_module.config.ADVERTISE_HOSTS
        worker_module.config.ADVERTISE_HOSTS = ("192.0.2.10", "198.51.100.10")
        try:
            self.assertEqual(advertise_host_for_tv("198.51.100.50"), "198.51.100.10")
            self.assertEqual(advertise_host_for_tv("192.0.2.50"), "192.0.2.10")
        finally:
            worker_module.config.ADVERTISE_HOSTS = original_hosts

    def test_stream_url_prefers_public_url(self):
        original_public_url = worker_module.config.PUBLIC_URL
        worker_module.config.PUBLIC_URL = "http://192.0.2.10:8098/"
        try:
            url = stream_url_for_tv("192.0.2.55", 7, "generic_dlna")
        finally:
            worker_module.config.PUBLIC_URL = original_public_url

        self.assertTrue(url.startswith("http://192.0.2.10:8098/stream/7?"))
        self.assertIn("profile=generic_dlna", url)

    def test_stream_url_repairs_quoted_public_url(self):
        original_public_url = worker_module.config.PUBLIC_URL
        worker_module.config.PUBLIC_URL = "http://'192.0.2.10:'8098'"
        try:
            url = stream_url_for_tv("192.0.2.55", 7, "generic_dlna")
        finally:
            worker_module.config.PUBLIC_URL = original_public_url

        self.assertTrue(url.startswith("http://192.0.2.10:8098/stream/7?"))
        self.assertNotIn("'", url)
        self.assertNotIn('"', url)

    def test_video_filter_pads_to_exact_frame(self):
        vf = video_filter({"fps": 30, "target_width": 1920, "target_height": 1080, "exact_frame": True})

        self.assertIn("scale=1920:1080:force_original_aspect_ratio=decrease", vf)
        self.assertIn("pad=1920:1080", vf)
        self.assertIn("setsar=1", vf)

    def test_security_tokens_are_signed(self):
        csrf = create_csrf_token()
        stream = create_stream_token(7, "generic_dlna")

        self.assertTrue(verify_csrf_token(csrf))
        self.assertFalse(verify_csrf_token(csrf + "x"))
        self.assertTrue(verify_stream_token(7, "generic_dlna", stream))
        self.assertFalse(verify_stream_token(8, "generic_dlna", stream))

    def test_stream_token_is_bound_to_tv_ip(self):
        stream = create_stream_token(7, "generic_dlna", "192.0.2.55")

        self.assertTrue(verify_stream_token(7, "generic_dlna", stream, "192.0.2.55"))
        self.assertFalse(verify_stream_token(7, "generic_dlna", stream, "192.0.2.66"))
        self.assertFalse(verify_stream_token(7, "generic_dlna", stream))

    def test_push_media_event_does_not_leak_stream_token(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "db.sqlite3")
            source = Path(tmp) / "clip.mp4"
            source.write_bytes(b"video")
            media_id = store.add_media("clip", source, "clip.mp4", 5, "c", duration_seconds=5)
            playlist_id = store.create_playlist("p")
            store.add_playlist_item(playlist_id, media_id)
            tv_id = store.add_tv("TV", "192.0.2.77", "generic_dlna")
            store.update_tv_config(tv_id, "TV", "192.0.2.77", "generic_dlna", playlist_id, True)
            store.set_tv_control_url(tv_id, "http://192.0.2.77:9197/control")
            worker = Worker(store)
            job = store.get_transcode(media_id, "generic_dlna")
            store.ensure_transcode_job(media_id, "generic_dlna")
            out = transcode_module.output_path(source, "generic_dlna")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"safe")
            job = store.get_transcode(media_id, "generic_dlna")
            store.mark_job_done(job["id"], media_id, out)

            pushed = {}

            def fake_push(control_url, media_url, *args, **kwargs):
                pushed["url"] = media_url
                return False

            original_push = worker_module.push_video
            worker_module.push_video = fake_push
            try:
                worker._push_next_locked(store.get_tv(tv_id))
            finally:
                worker_module.push_video = original_push

            self.assertIn("token=", pushed["url"])
            event = store.list_events(tv_id, "push_media", 1)[0]
            self.assertNotIn("token=", event["details"] or "")

    def test_csrf_can_be_bound_to_session_token(self):
        token = create_csrf_token("session-a")

        self.assertTrue(verify_csrf_token(token, "session-a"))
        self.assertFalse(verify_csrf_token(token, "session-b"))

    def test_store_sets_playlist_item_position_directly(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            source = Path(tmp) / "clip.mp4"
            source.write_bytes(b"video")
            media_ids = [store.add_media(f"m{i}", source, f"m{i}.mp4", 5, str(i)) for i in range(4)]
            playlist_id = store.create_playlist("p")
            for media_id in media_ids:
                store.add_playlist_item(playlist_id, media_id)
            items = store.playlist_items(playlist_id)

            store.set_playlist_item_position(items[3]["id"], 0)
            reordered = [item["media_id"] for item in store.playlist_items(playlist_id)]
            self.assertEqual(reordered, [media_ids[3], media_ids[0], media_ids[1], media_ids[2]])

            store.set_playlist_item_position(items[3]["id"], 2)
            reordered = [item["media_id"] for item in store.playlist_items(playlist_id)]
            self.assertEqual(reordered, [media_ids[0], media_ids[1], media_ids[3], media_ids[2]])
            self.assertEqual([item["position"] for item in store.playlist_items(playlist_id)], [0, 1, 2, 3])

    def test_session_sliding_renewal_capped_by_max_lifetime(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            user_id = store.create_user("sliding", "password-123", "admin")
            token = store.create_session(user_id, "192.0.2.1", "agent")

            store.execute("UPDATE sessions SET expires_at = expires_at - 3600")
            aged = store.row("SELECT expires_at FROM sessions")["expires_at"]
            store.get_session_user(token)
            renewed = store.row("SELECT expires_at FROM sessions")["expires_at"]
            self.assertGreater(renewed, aged)

            # ApiTests reloads screenloop modules to isolate environment-based
            # configuration. Patch the globals used by this exact Store class,
            # not whichever module object currently occupies sys.modules.
            store_globals = Store.get_session_user.__globals__
            original = store_globals["SESSION_MAX_LIFETIME_SECONDS"]
            store_globals["SESSION_MAX_LIFETIME_SECONDS"] = 10
            try:
                store.get_session_user(token)
                capped = store.row("SELECT expires_at FROM sessions")["expires_at"]
            finally:
                store_globals["SESSION_MAX_LIFETIME_SECONDS"] = original
            self.assertEqual(capped, renewed)

    def test_node_agent_stream_tokens_and_cache_prune(self):
        from screenloop import node_agent

        agent = node_agent.NodeAgent()
        agent.token = "unit-node-token"

        expires_at = int(time.time()) + 60
        token = f"{expires_at}:{agent.sign_stream(5, 'lg_webos', '10.0.0.5', expires_at)}"
        self.assertTrue(agent.verify_stream(5, "lg_webos", token, "10.0.0.5"))
        self.assertFalse(agent.verify_stream(5, "lg_webos", token, "10.0.0.6"))
        self.assertFalse(agent.verify_stream(6, "lg_webos", token, "10.0.0.5"))
        expired_at = int(time.time()) - 10
        expired = f"{expired_at}:{agent.sign_stream(5, 'lg_webos', '10.0.0.5', expired_at)}"
        self.assertFalse(agent.verify_stream(5, "lg_webos", expired, "10.0.0.5"))

        with TemporaryDirectory() as tmp:
            original_cache = node_agent.CACHE_DIR
            node_agent.CACHE_DIR = Path(tmp)
            try:
                keep = agent.cache_path(1, "lg_webos", "aaaa")
                drop = agent.cache_path(2, "lg_webos", "bbbb")
                keep.write_bytes(b"0" * 100)
                drop.write_bytes(b"0" * 100)

                agent.prune_cache({keep.name})

                self.assertTrue(keep.exists())
                self.assertFalse(drop.exists())
                self.assertEqual(agent.cached_file(1, "lg_webos"), keep)
                self.assertIsNone(agent.cached_file(2, "lg_webos"))
            finally:
                node_agent.CACHE_DIR = original_cache

    def test_node_agent_stops_playback_outside_effective_schedule(self):
        from screenloop import node_agent

        agent = node_agent.NodeAgent()
        tv = {
            "id": 7,
            "ip": "192.0.2.7",
            "autoplay": True,
            "schedule": {"mode": "custom", "days": "", "start": "08:00", "end": "18:00"},
        }
        agent.tvs = {7: tv}
        agent.runtime = {
            7: {
                "media_id": 9,
                "started_at": time.time(),
                "duration": 3600,
                "control_url": "http://tv/control",
            }
        }

        with (
            mock.patch.object(node_agent, "host_ping_reachable", return_value=True),
            mock.patch.object(node_agent, "stop_strict", return_value=True),
        ):
            status = agent.poll_tv(tv)

        self.assertIsNone(agent.runtime[7]["media_id"])
        self.assertEqual(status["state"], "STOPPED")

    def test_node_agent_invalid_timezone_uses_controller_offset(self):
        from screenloop import node_agent

        timezone = node_agent.NodeAgent._config_timezone(
            {"schedule_timezone": "/not/a/zone", "schedule_utc_offset": 10_800}
        )

        self.assertEqual(timezone.utcoffset(None).total_seconds(), 10_800)

    def test_refuses_placeholder_secrets(self):
        from screenloop import config

        original_secret = config.SECRET_KEY
        original_password = config.BOOTSTRAP_PASSWORD
        original_insecure = config.ALLOW_INSECURE_AUTH
        try:
            config.ALLOW_INSECURE_AUTH = False
            config.SECRET_KEY = "change-this-to-a-long-random-secret"
            with self.assertRaises(RuntimeError):
                config.validate_security_config()

            config.SECRET_KEY = "unit-secret-4f9d2c81e7b3a650"
            config.validate_security_config()

            config.BOOTSTRAP_PASSWORD = "change-this-to-a-long-random-password"
            with self.assertRaises(RuntimeError):
                config.validate_bootstrap_password()

            config.BOOTSTRAP_PASSWORD = "dev-password-please-change"
            with self.assertRaises(RuntimeError):
                config.validate_bootstrap_password()

            config.BOOTSTRAP_PASSWORD = "unit-Adm1n-4f9d2c81"
            config.validate_bootstrap_password()
        finally:
            config.SECRET_KEY = original_secret
            config.BOOTSTRAP_PASSWORD = original_password
            config.ALLOW_INSECURE_AUTH = original_insecure


class TvGroupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.store = Store(Path(self._tmp.name) / "test.sqlite3")
        # Организация → Филиал → Этаж, три уровня.
        self.org = self.store.create_group("Организация")
        self.branch = self.store.create_group("Филиал Север", self.org)
        self.floor = self.store.create_group("Этаж 2", self.branch)
        self.other_branch = self.store.create_group("Филиал Юг", self.org)

    def tearDown(self):
        self._tmp.cleanup()

    def test_groups_default_to_inheriting_schedule(self):
        group = self.store.get_group(self.floor)

        self.assertEqual(group.get("schedule_mode"), "inherit")
        self.assertIsNone(group.get("schedule_days"))
        self.assertIsNone(group.get("schedule_start"))
        self.assertIsNone(group.get("schedule_end"))

    def test_tv_contains_nearest_first_group_schedule_chain(self):
        self.store.execute(
            """
            UPDATE tv_groups
            SET schedule_mode = ?, schedule_days = ?, schedule_start = ?, schedule_end = ?
            WHERE id = ?
            """,
            ("custom", "0,1,2,3,4", "08:00", "18:00", self.org),
        )
        self.store.execute(
            "UPDATE tv_groups SET schedule_mode = ? WHERE id = ?",
            ("always", self.floor),
        )
        tv_id = self.store.add_tv("Lobby", "192.0.2.80", "generic_dlna")
        self.store.set_tv_group(tv_id, self.floor)

        tv = next(tv for tv in self.store.list_tvs() if tv["id"] == tv_id)

        self.assertEqual(
            [group["id"] for group in tv.get("schedule_groups", [])],
            [self.floor, self.branch, self.org],
        )
        self.assertEqual(tv["schedule_groups"][0]["schedule_mode"], "always")
        self.assertEqual(tv["schedule_groups"][2]["schedule_start"], "08:00")

    def test_moving_group_changes_tv_schedule_chain_without_copying(self):
        tv_id = self.store.add_tv("Lobby", "192.0.2.81", "generic_dlna")
        self.store.set_tv_group(tv_id, self.floor)

        self.store.update_group(self.floor, None, self.other_branch, True)
        tv = self.store.get_tv(tv_id)

        self.assertEqual(
            [group["id"] for group in tv.get("schedule_groups", [])],
            [self.floor, self.other_branch, self.org],
        )
        self.assertEqual(tv["schedule_mode"], "inherit")

    def test_tree_lists_depth_and_path_in_display_order(self):
        groups = {group["name"]: group for group in self.store.list_groups()}

        self.assertEqual(groups["Организация"]["depth"], 0)
        self.assertEqual(groups["Филиал Север"]["depth"], 1)
        self.assertEqual(groups["Этаж 2"]["depth"], 2)
        self.assertEqual(groups["Этаж 2"]["path"], "Организация / Филиал Север / Этаж 2")
        # Дети идут сразу за своим родителем, а не в конце списка.
        order = [group["name"] for group in self.store.list_groups()]
        self.assertEqual(order.index("Этаж 2"), order.index("Филиал Север") + 1)

    def test_subtree_and_ancestors_span_three_levels(self):
        self.assertEqual(sorted(self.store.group_subtree_ids(self.org)), sorted([self.org, self.branch, self.floor, self.other_branch]))
        self.assertEqual(sorted(self.store.group_subtree_ids(self.branch)), sorted([self.branch, self.floor]))
        self.assertEqual(self.store.group_subtree_ids(self.floor), [self.floor])

        # Ближайший предок первым — от этого зависит разрешение плейлиста.
        self.assertEqual(self.store.group_ancestors(self.floor), [self.floor, self.branch, self.org])
        self.assertEqual(self.store.group_ancestors(self.org), [self.org])
        self.assertEqual(self.store.group_depth(self.floor), 3)
        self.assertEqual(self.store.group_depth(None), 0)

    def test_moving_a_group_into_its_own_descendant_is_detectable(self):
        # Сам store не запрещает — это делает роут, опираясь на group_subtree_ids.
        self.assertIn(self.floor, self.store.group_subtree_ids(self.branch))
        self.assertNotIn(self.other_branch, self.store.group_subtree_ids(self.branch))

    def test_moving_a_group_reparents_the_whole_branch(self):
        self.store.move_group(self.branch, self.other_branch)

        self.assertEqual(self.store.group_ancestors(self.floor), [self.floor, self.branch, self.other_branch, self.org])
        self.assertIn(self.floor, self.store.group_subtree_ids(self.other_branch))

    def test_group_names_are_unique_per_parent_but_not_globally(self):
        self.store.create_group("Этаж 2", self.other_branch)  # то же имя в другом филиале — можно

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_group("Этаж 2", self.branch)

    def test_root_group_names_are_unique(self):
        # NULL != NULL в SQLite, поэтому обычный UNIQUE(parent_id, name) это бы пропустил.
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_group("Организация")

    def test_deleting_a_group_removes_children_but_keeps_tvs(self):
        tv_id = self.store.add_tv("Холл", "192.0.2.10", "generic_dlna")
        self.store.set_tv_group(tv_id, self.floor)

        self.store.delete_group(self.branch)

        self.assertIsNone(self.store.get_group(self.branch))
        self.assertIsNone(self.store.get_group(self.floor))
        tv = self.store.get_tv(tv_id)
        self.assertIsNotNone(tv, "телевизор не должен исчезать вместе с группой")
        self.assertIsNone(tv["group_id"])

    def test_list_tvs_exposes_the_group_name(self):
        tv_id = self.store.add_tv("Холл", "192.0.2.11", "generic_dlna")
        self.store.set_tv_group(tv_id, self.floor)

        tv = self.store.list_tvs()[0]

        self.assertEqual(tv["group_id"], self.floor)
        self.assertEqual(tv["group_name"], "Этаж 2")


VALID_TEMPLATE = b"""
name = "Sony Bravia X-series"
match = ["sony", "bravia"]
probe_port = 52323

[ffmpeg]
video_codec = "libx264"
audio_codec = "aac"
max_width = 1920
max_height = 1080
fps = 30
crf = 22
maxrate = "12000k"
bufsize = "24000k"
audio_bitrate = "160k"
"""


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._original_dir = config_module.PROFILES_DIR
        self.profiles_dir = Path(self._tmp.name)
        config_module.PROFILES_DIR = self.profiles_dir
        profiles_module.config.PROFILES_DIR = self.profiles_dir
        reload_profiles()

    def tearDown(self):
        config_module.PROFILES_DIR = self._original_dir
        profiles_module.config.PROFILES_DIR = self._original_dir
        reload_profiles()
        self._tmp.cleanup()

    def write(self, name: str, body: bytes) -> Path:
        path = self.profiles_dir / name
        path.write_bytes(body)
        return path

    def test_builtin_ffmpeg_settings_are_unchanged(self):
        # The transcode cache filename embeds a sha1 of the ffmpeg dict
        # (transcode.output_path), so any drift here silently invalidates every
        # already-transcoded file in production.
        expected = {
            "generic_dlna": ("high", "4.1", "12000k", "24000k", "160k", 9197),
            "lg_netcast": ("high", "4.1", "12000k", "24000k", "160k", 1925),
            "lg_webos": ("high", "4.1", "12000k", "24000k", "160k", 9197),
            "samsung_tizen": ("high", "4.1", "14000k", "28000k", "160k", 8001),
            "samsung_legacy": ("main", "4.0", "8000k", "16000k", "128k", 7676),
        }
        self.assertEqual(set(PROFILES), set(expected))
        for key, (h264_profile, level, maxrate, bufsize, audio, probe_port) in expected.items():
            ffmpeg = PROFILES[key]["ffmpeg"]
            self.assertEqual(PROFILES[key]["source"], "builtin")
            self.assertEqual(PROFILES[key]["probe_port"], probe_port)
            self.assertEqual(ffmpeg["h264_profile"], h264_profile)
            self.assertEqual(ffmpeg["h264_level"], level)
            self.assertEqual(ffmpeg["maxrate"], maxrate)
            self.assertEqual(ffmpeg["bufsize"], bufsize)
            self.assertEqual(ffmpeg["audio_bitrate"], audio)
            self.assertEqual(ffmpeg["container"], "mp4")
            self.assertEqual(ffmpeg["video_codec"], "libx264")
            self.assertEqual(ffmpeg["audio_codec"], "aac")
            self.assertEqual(ffmpeg["audio_sample_rate"], 48000)
            self.assertEqual(ffmpeg["fps"], 30)
            self.assertEqual(ffmpeg["crf"], 22)
            self.assertIs(ffmpeg["add_silent_audio"], True)
            self.assertIs(ffmpeg["exact_frame"], True)
            self.assertEqual(ffmpeg["max_width"], 1920)
            self.assertEqual(ffmpeg["max_height"], 1080)
            self.assertEqual(ffmpeg["target_width"], 1920)
            self.assertEqual(ffmpeg["target_height"], 1080)
        self.assertIn("DLNA.ORG_PN=AVC_MP4_MP_HD_1080i_AAC", PROFILES["samsung_legacy"]["dlna_protocol_info"])

    def test_custom_template_is_loaded_and_detected(self):
        self.write("sony_bravia.toml", VALID_TEMPLATE)
        self.assertEqual(reload_profiles(), [])
        self.assertIn("sony_bravia", PROFILES)
        self.assertEqual(PROFILES["sony_bravia"]["source"], "custom")
        self.assertEqual(PROFILES["sony_bravia"]["name"], "Sony Bravia X-series")
        self.assertEqual(PROFILES["sony_bravia"]["probe_port"], 52323)
        self.assertEqual(detect_profile("Sony", "BRAVIA KD-55"), "sony_bravia")
        self.assertEqual(profile_or_default("sony_bravia"), "sony_bravia")

    def test_optional_ffmpeg_fields_fall_back_to_defaults(self):
        self.write("sony_bravia.toml", VALID_TEMPLATE)
        reload_profiles()
        ffmpeg = PROFILES["sony_bravia"]["ffmpeg"]
        self.assertEqual(ffmpeg["h264_profile"], "high")
        self.assertEqual(ffmpeg["h264_level"], "4.1")
        self.assertEqual(ffmpeg["target_width"], 1920)
        self.assertEqual(ffmpeg["target_height"], 1080)
        self.assertIs(ffmpeg["exact_frame"], False)
        self.assertNotIn("dlna_protocol_info", PROFILES["sony_bravia"])

    def test_priority_orders_ambiguous_matches(self):
        # samsung_tizen must win over samsung_legacy, which also matches "samsung".
        self.assertEqual(detect_profile("Samsung", "Tizen"), "samsung_tizen")
        self.write("aaa_vendor.toml", VALID_TEMPLATE.replace(b'["sony", "bravia"]', b'["bravia"]'))
        self.write(
            "zzz_vendor.toml",
            VALID_TEMPLATE.replace(b'["sony", "bravia"]', b'["bravia"]\npriority = 5'),
        )
        reload_profiles()
        self.assertEqual(detect_profile("BRAVIA"), "zzz_vendor")

    def test_broken_template_is_reported_and_skipped(self):
        self.write("broken.toml", b"name = \nthis is not toml")
        self.write("sony_bravia.toml", VALID_TEMPLATE)
        errors = reload_profiles()
        self.assertEqual(len(errors), 1)
        self.assertIn("broken.toml", errors[0])
        self.assertIn("invalid TOML", errors[0])
        self.assertNotIn("broken", PROFILES)
        self.assertIn("sony_bravia", PROFILES)

    def test_custom_template_cannot_shadow_a_builtin(self):
        self.write("lg_webos.toml", VALID_TEMPLATE)
        errors = reload_profiles()
        self.assertEqual(len(errors), 1)
        self.assertIn("collides with the built-in template", errors[0])
        self.assertEqual(PROFILES["lg_webos"]["source"], "builtin")
        self.assertEqual(PROFILES["lg_webos"]["name"], "LG webOS")

    def test_missing_required_field_is_rejected(self):
        errors = validate_template({"name": "X", "ffmpeg": {"video_codec": "libx264"}}, "x")
        self.assertIn("ffmpeg.audio_codec is required", errors)
        self.assertIn("ffmpeg.crf is required", errors)
        self.assertNotIn("name is required and must be a non-empty string", errors)

    def test_out_of_range_values_are_rejected(self):
        data = {
            "name": "X",
            "probe_port": 70000,
            "ffmpeg": {
                "video_codec": "libx264",
                "audio_codec": "aac",
                "max_width": 99999,
                "max_height": 1080,
                "fps": 300,
                "crf": 99,
                "maxrate": "fast",
                "bufsize": "24000k",
                "audio_bitrate": "160k",
            },
        }
        errors = validate_template(data, "x")
        self.assertIn("ffmpeg.max_width must be between 320 and 3840", errors)
        self.assertIn("ffmpeg.fps must be between 1 and 60", errors)
        self.assertIn("ffmpeg.crf must be between 0 and 51", errors)
        self.assertIn("ffmpeg.maxrate must look like '12000k'", errors)
        self.assertIn("probe_port must be an integer between 1 and 65535", errors)

    def test_codecs_are_allow_listed(self):
        data = {
            "name": "X",
            "ffmpeg": {
                "video_codec": "libx265",
                "audio_codec": "mp3",
                "max_width": 1920,
                "max_height": 1080,
                "fps": 30,
                "crf": 22,
                "maxrate": "12000k",
                "bufsize": "24000k",
                "audio_bitrate": "160k",
            },
        }
        errors = validate_template(data, "x")
        self.assertTrue(any("video_codec must be one of" in error for error in errors))
        self.assertTrue(any("audio_codec must be one of" in error for error in errors))

    def test_invalid_id_is_rejected(self):
        for bad_id in ("../escape", "Upper", "with space", "", "x" * 41):
            self.assertTrue(
                any("must match [a-z0-9_]" in error for error in validate_template({"name": "X"}, bad_id)),
                bad_id,
            )

    def test_oversized_template_is_rejected(self):
        with self.assertRaises(TemplateError) as ctx:
            parse_template(b"x" * (16 * 1024 + 1), "big")
        self.assertIn("larger than", ctx.exception.errors[0])

    def test_non_utf8_template_is_rejected(self):
        with self.assertRaises(TemplateError) as ctx:
            parse_template(b"\xff\xfe name = 'x'", "bad")
        self.assertIn("UTF-8", ctx.exception.errors[0])

    def test_missing_default_profile_is_fatal(self):
        original = profiles_module.BUILTIN_DIR
        profiles_module.BUILTIN_DIR = self.profiles_dir
        try:
            with self.assertRaises(RuntimeError):
                reload_profiles()
        finally:
            profiles_module.BUILTIN_DIR = original
            reload_profiles()


if __name__ == "__main__":
    unittest.main()
