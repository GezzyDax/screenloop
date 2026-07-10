import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from screenloop.dlna import make_didl, parse_ssdp_response
from screenloop.profiles import PROFILES, detect_profile, profile_or_default
from screenloop.security import create_csrf_token, create_stream_token, verify_csrf_token, verify_stream_token
from screenloop.store import Store
from screenloop.transcode import compressed_profile, output_path, video_filter
from screenloop import transcode as transcode_module
from screenloop import worker as worker_module
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

    def test_session_sliding_renewal_capped_by_max_lifetime(self):
        import screenloop.store as store_module

        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            user_id = store.create_user("sliding", "password-123", "admin")
            token = store.create_session(user_id, "192.0.2.1", "agent")

            store.execute("UPDATE sessions SET expires_at = expires_at - 3600")
            aged = store.row("SELECT expires_at FROM sessions")["expires_at"]
            store.get_session_user(token)
            renewed = store.row("SELECT expires_at FROM sessions")["expires_at"]
            self.assertGreater(renewed, aged)

            original = store_module.SESSION_MAX_LIFETIME_SECONDS
            store_module.SESSION_MAX_LIFETIME_SECONDS = 10
            try:
                store.get_session_user(token)
                capped = store.row("SELECT expires_at FROM sessions")["expires_at"]
            finally:
                store_module.SESSION_MAX_LIFETIME_SECONDS = original
            self.assertEqual(capped, renewed)

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


if __name__ == "__main__":
    unittest.main()
