import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from screenloop.dlna import make_didl, parse_ssdp_response
from screenloop.profiles import detect_profile, profile_or_default
from screenloop.security import create_csrf_token, create_stream_token, verify_csrf_token, verify_stream_token
from screenloop.store import Store
from screenloop.transcode import output_path, video_filter
from screenloop import worker as worker_module
from screenloop.worker import Worker, advertise_host_for_tv


class CoreTests(unittest.TestCase):
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

    def test_store_event_retention_keeps_last_1000(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            for index in range(1005):
                store.add_event(None, "test", f"event {index}")

            events = store.list_events(limit=1100)

            self.assertEqual(len(events), 1000)
            self.assertEqual(events[0]["message"], "event 1004")
            self.assertEqual(events[-1]["message"], "event 5")

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

    def test_silent_output_path_differs_from_audible(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"video")

            audible = output_path(source, "generic_dlna", silent=False)
            silent = output_path(source, "generic_dlna", silent=True)

            self.assertNotEqual(audible, silent)
            self.assertIn(".silent.", silent.name)
            self.assertNotIn(".silent.", audible.name)

    def test_store_silent_flag_requeues_transcode_jobs(self):
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
            store.requeue_transcode_jobs_for_media(media_id)

            refreshed = store.get_transcode(media_id, "generic_dlna")
            media = store.get_media(media_id)
            self.assertEqual(media["silent"], 1)
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

    def test_csrf_can_be_bound_to_session_token(self):
        token = create_csrf_token("session-a")

        self.assertTrue(verify_csrf_token(token, "session-a"))
        self.assertFalse(verify_csrf_token(token, "session-b"))


if __name__ == "__main__":
    unittest.main()
