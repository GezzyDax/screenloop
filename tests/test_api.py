import importlib
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local bare Python may not have app deps.
    TestClient = None


TEST_ADMIN_PASSWORD = "unit-Adm1n-4f9d2c81"
TEST_SECRET_KEY = "unit-secret-4f9d2c81e7b3a650"


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed")
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ.update(
            {
                "SCREENLOOP_DATA_DIR": str(root),
                "SCREENLOOP_DB_PATH": str(root / "db.sqlite3"),
                "SCREENLOOP_MEDIA_DIR": str(root / "media"),
                "SCREENLOOP_TRANSCODE_DIR": str(root / "transcoded"),
                "SCREENLOOP_BOOTSTRAP_USER": "admin",
                "SCREENLOOP_BOOTSTRAP_PASSWORD": TEST_ADMIN_PASSWORD,
                "SCREENLOOP_SECRET_KEY": TEST_SECRET_KEY,
                "SCREENLOOP_ALLOWED_TV_CIDRS": "192.0.2.0/24",
            }
        )
        for name in list(sys.modules):
            if name == "screenloop" or name.startswith("screenloop."):
                sys.modules.pop(name, None)
        self.web = importlib.import_module("screenloop.web")
        self.web.config.ensure_dirs()
        self.web.config.validate_security_config()
        self.web.config.validate_bootstrap_password()
        self.web.store.ensure_bootstrap_admin("admin", TEST_ADMIN_PASSWORD)
        self.client = TestClient(self.web.app)
        self.csrf = self.login("admin", TEST_ADMIN_PASSWORD)["csrf_token"]

    def tearDown(self):
        self.tmp.cleanup()

    def login(self, username: str, password: str) -> dict:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("screenloop_session", self.client.cookies)
        return response.json()

    def post(self, url: str, payload: dict | None = None):
        return self.client.post(url, json=payload or {}, headers={"X-CSRF-Token": self.csrf})

    def patch(self, url: str, payload: dict):
        return self.client.patch(url, json=payload, headers={"X-CSRF-Token": self.csrf})

    def delete(self, url: str):
        return self.client.delete(url, headers={"X-CSRF-Token": self.csrf})

    def test_session_and_status_require_auth(self):
        anonymous = TestClient(self.web.app)

        self.assertEqual(anonymous.get("/api/v1/session").status_code, 401)
        session = self.client.get("/api/v1/session")
        status = self.client.get("/api/v1/status")
        version = self.client.get("/api/v1/version")
        diagnostics = self.client.get("/api/v1/diagnostics")

        self.assertEqual(session.status_code, 200)
        self.assertEqual(session.json()["user"]["role"], "admin")
        self.assertIn("csrf_token", session.json())
        self.assertEqual(status.status_code, 200)
        self.assertIn("tvs", status.json())
        self.assertEqual(version.status_code, 200)
        self.assertIn("version", version.json())
        self.assertEqual(diagnostics.status_code, 200)
        self.assertIn("workers", diagnostics.json())

    def test_stream_range_helpers_detect_near_end(self):
        self.assertEqual(self.web.parse_range_header("bytes=100-199", 1000), (100, 199))
        self.assertEqual(self.web.parse_range_header("bytes=900-", 1000), (900, 999))
        self.assertIsNone(self.web.parse_range_header("bytes=1000-1200", 1000))
        self.assertIsNone(self.web.parse_range_header("bytes=bad-range", 1000))

        self.assertTrue(self.web.stream_range_near_end(999, 1000))
        self.assertFalse(self.web.stream_range_near_end(50, 200 * 1024 * 1024))

    def test_stream_get_syncs_tv_playback_state(self):
        source = Path(self.tmp.name) / "clip.mp4"
        source.write_bytes(b"video")
        first_media = self.web.store.add_media("first", source, "first.mp4", source.stat().st_size, "a", duration_seconds=10)
        second_media = self.web.store.add_media("second", source, "second.mp4", source.stat().st_size, "b", duration_seconds=20)
        playlist_id = self.web.store.create_playlist("playlist")
        self.web.store.add_playlist_item(playlist_id, first_media)
        self.web.store.add_playlist_item(playlist_id, second_media)
        tv_id = self.web.store.add_tv("TV", "192.0.2.55", "lg_webos")
        self.web.store.update_tv_config(tv_id, "TV", "192.0.2.55", "lg_webos", playlist_id, True)
        self.web.store.set_tv_playback_position(tv_id, 1, first_media)
        self.web.store.update_tv_status(tv_id, False, "ERROR", "timed out")
        self.web.store.add_event(
            tv_id,
            "push_media",
            "Push second",
            self.web.event_details(media_id=second_media, index=1, url="http://screenloop.test/stream/2?token=secret"),
        )
        scheduled = []
        preloaded = []
        original_schedule = self.web.schedule_stream_auto_advance
        original_preload = self.web.preload_following_uri_async

        self.web.schedule_stream_auto_advance = lambda tv_id, media_id, duration: scheduled.append((tv_id, media_id, duration))
        self.web.preload_following_uri_async = lambda tv_id, media_id, sync_event_id=None: preloaded.append((tv_id, media_id, sync_event_id))
        try:
            self.assertFalse(self.web.sync_tv_playback_from_stream(second_media, "192.0.2.55", "HEAD"))
            self.assertTrue(self.web.sync_tv_playback_from_stream(second_media, "192.0.2.55", "GET"))
        finally:
            self.web.schedule_stream_auto_advance = original_schedule
            self.web.preload_following_uri_async = original_preload
        tv = self.web.store.get_tv(tv_id)

        self.assertEqual(tv["current_media_id"], second_media)
        self.assertEqual(tv["current_index"], 0)
        self.assertEqual(tv["playback_state"], "PLAYING")
        self.assertEqual(tv["online"], 1)
        self.assertEqual(tv["ping_reachable"], 1)
        self.assertEqual(tv["dlna_reachable"], 1)
        self.assertEqual(tv["streaming"], 1)
        self.assertIsNone(tv["last_error"])
        self.assertEqual(preloaded[0][:2], (tv_id, second_media))
        self.assertIsInstance(preloaded[0][2], int)
        self.assertEqual(scheduled, [(tv_id, second_media, 20)])
        event = self.web.store.list_events(tv_id, "stream_playback_sync", 1)[0]
        self.assertIn(str(second_media), event["message"])
        self.assertIn(f"media_id={second_media}", event["details"])
        self.assertIn("push_delay_s=", event["details"])
        self.assertIn("timer_delay_s=25", event["details"])

    def test_stream_timer_queues_next_without_waiting_for_poll(self):
        source = Path(self.tmp.name) / "clip.mp4"
        source.write_bytes(b"video")
        first_media = self.web.store.add_media("first", source, "first.mp4", source.stat().st_size, "a", duration_seconds=10)
        second_media = self.web.store.add_media("second", source, "second.mp4", source.stat().st_size, "b", duration_seconds=20)
        playlist_id = self.web.store.create_playlist("playlist")
        self.web.store.add_playlist_item(playlist_id, first_media)
        self.web.store.add_playlist_item(playlist_id, second_media)
        tv_id = self.web.store.add_tv("TV", "192.0.2.56", "lg_webos")
        self.web.store.update_tv_config(tv_id, "TV", "192.0.2.56", "lg_webos", playlist_id, True)
        self.web.store.set_tv_playback_position(tv_id, 1, first_media)
        started_at = self.web.store.get_tv(tv_id)["playback_started_at"]

        self.assertTrue(self.web.enqueue_stream_auto_advance(tv_id, first_media, started_at, 10))
        command = self.web.store.next_pending_command()
        self.assertEqual(command["command"], "play_next")
        event = self.web.store.list_events(tv_id, "duration_elapsed", 1)[0]
        self.assertIn("stream_timer", event["details"])
        self.assertIn(f"media_id={first_media}", event["details"])
        self.assertIn("fired_after_s=", event["details"])
        self.assertIn("late_by_s=", event["details"])

    def test_stream_preload_sets_following_uri(self):
        source = Path(self.tmp.name) / "clip.mp4"
        source.write_bytes(b"video")
        first_media = self.web.store.add_media("first", source, "first.mp4", source.stat().st_size, "a", duration_seconds=10)
        second_media = self.web.store.add_media("second", source, "second.mp4", source.stat().st_size, "b", duration_seconds=20)
        playlist_id = self.web.store.create_playlist("playlist")
        self.web.store.add_playlist_item(playlist_id, first_media)
        self.web.store.add_playlist_item(playlist_id, second_media)
        tv_id = self.web.store.add_tv("TV", "192.0.2.57", "lg_webos")
        self.web.store.update_tv_config(
            tv_id,
            "TV",
            "192.0.2.57",
            "lg_webos",
            playlist_id,
            True,
            "http://192.0.2.57:9197/AVTransport/control",
        )
        self.web.store.set_tv_playback_position(tv_id, 1, first_media)
        calls = []
        original_public_url = self.web.config.PUBLIC_URL
        original_set_next_uri = self.web.set_next_uri

        def fake_set_next_uri(control_url, media_url, title, mime_type, protocol_info=None):
            calls.append((control_url, media_url, title, mime_type, protocol_info))

        self.web.config.PUBLIC_URL = "http://screenloop.test"
        self.web.set_next_uri = fake_set_next_uri
        try:
            self.assertTrue(self.web.preload_following_uri(tv_id, first_media))
        finally:
            self.web.set_next_uri = original_set_next_uri
            self.web.config.PUBLIC_URL = original_public_url

        self.assertEqual(calls[0][0], "http://192.0.2.57:9197/AVTransport/control")
        self.assertIn(f"/stream/{second_media}", calls[0][1])
        self.assertEqual(calls[0][2], "second")
        event = self.web.store.list_events(tv_id, "preload_next_uri", 1)[0]
        self.assertIn(str(second_media), event["message"])
        self.assertIn(f"media_id={first_media}", event["details"])
        self.assertIn(f"target_media_id={second_media}", event["details"])
        self.assertIn("preload_delay_s=", event["details"])

    def test_live_stream_requires_auth_and_snapshot_shape(self):
        anonymous = TestClient(self.web.app)

        self.assertEqual(anonymous.get("/api/v1/stream/events").status_code, 401)
        snapshot = self.web.live_snapshot()
        self.assertIn("status", snapshot)
        self.assertIn("events", snapshot)
        self.assertIn("tvs", snapshot["status"])
        self.assertIn("transcode_jobs", snapshot["status"])

    def test_diagnostics_treats_container_docker_cli_as_host_managed(self):
        original_run_probe = self.web.run_probe
        os.environ["SCREENLOOP_CONTAINER"] = "1"

        def fake_run_probe(command, timeout=3):
            if command[0] == "docker":
                return {"ok": False, "returncode": None, "output": ["not installed"]}
            return original_run_probe(command, timeout)

        self.web.run_probe = fake_run_probe
        try:
            response = self.client.get("/api/v1/diagnostics")
        finally:
            self.web.run_probe = original_run_probe
            os.environ.pop("SCREENLOOP_CONTAINER", None)

        self.assertEqual(response.status_code, 200, response.text)
        probes = response.json()["probes"]
        self.assertEqual(probes["docker"]["status"], "host_managed")
        self.assertEqual(probes["docker_compose"]["status"], "host_managed")

    def test_unsafe_api_requires_csrf(self):
        response = self.client.post("/api/v1/playlists", json={"name": "No CSRF"})

        self.assertEqual(response.status_code, 403)

    def test_health_does_not_expose_version(self):
        anonymous = TestClient(self.web.app)
        response = anonymous.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_tv_control_url_must_be_http_and_inside_allowed_cidr(self):
        tv = self.post("/api/v1/tvs", {"name": "TV", "ip": "192.0.2.55", "profile": "generic_dlna"}).json()

        https_response = self.patch(
            f"/api/v1/tvs/{tv['id']}",
            {"name": "TV", "ip": "192.0.2.55", "profile": "generic_dlna", "control_url": "https://192.0.2.55:9197/control"},
        )
        outside_response = self.patch(
            f"/api/v1/tvs/{tv['id']}",
            {"name": "TV", "ip": "192.0.2.55", "profile": "generic_dlna", "control_url": "http://198.51.100.7:9197/control"},
        )
        allowed_response = self.patch(
            f"/api/v1/tvs/{tv['id']}",
            {"name": "TV", "ip": "192.0.2.55", "profile": "generic_dlna", "control_url": "http://192.0.2.55:9197/control"},
        )

        self.assertEqual(https_response.status_code, 400)
        self.assertEqual(outside_response.status_code, 403)
        self.assertEqual(allowed_response.status_code, 200, allowed_response.text)

    def test_upload_rejects_oversized_file_while_streaming(self):
        original_limit = self.web.config.MAX_UPLOAD_BYTES
        self.web.config.MAX_UPLOAD_BYTES = 16
        try:
            response = self.client.post(
                "/api/v1/media/upload",
                files={"file": ("clip.mp4", b"0" * 64, "video/mp4")},
                headers={"X-CSRF-Token": self.csrf},
            )
        finally:
            self.web.config.MAX_UPLOAD_BYTES = original_limit

        self.assertEqual(response.status_code, 413)
        leftovers = list(self.web.config.MEDIA_DIR.glob("clip.*"))
        self.assertEqual(leftovers, [])

    def test_upload_rejects_when_disk_space_is_low(self):
        original_min_free = self.web.config.MIN_FREE_DISK_BYTES
        self.web.config.MIN_FREE_DISK_BYTES = 10**18
        try:
            response = self.client.post(
                "/api/v1/media/upload",
                files={"file": ("clip.mp4", b"0" * 64, "video/mp4")},
                headers={"X-CSRF-Token": self.csrf},
            )
        finally:
            self.web.config.MIN_FREE_DISK_BYTES = original_min_free

        self.assertEqual(response.status_code, 507)

    def test_admin_can_manage_tv_playlist_and_commands(self):
        tv_response = self.post(
            "/api/v1/tvs",
            {"name": "Lobby", "ip": "192.0.2.55", "profile": "generic_dlna"},
        )
        playlist_response = self.post("/api/v1/playlists", {"name": "Main"})

        self.assertEqual(tv_response.status_code, 200, tv_response.text)
        self.assertEqual(playlist_response.status_code, 200, playlist_response.text)
        tv_id = tv_response.json()["id"]
        playlist_id = playlist_response.json()["id"]

        update = self.patch(
            f"/api/v1/tvs/{tv_id}",
            {
                "name": "Lobby",
                "ip": "192.0.2.55",
                "profile": "generic_dlna",
                "playlist_id": playlist_id,
                "autoplay": True,
                "control_url": "",
            },
        )
        command = self.post(f"/api/v1/tvs/{tv_id}/commands", {"command": "play_next"})

        self.assertEqual(update.status_code, 200, update.text)
        self.assertEqual(command.status_code, 200, command.text)
        self.assertTrue(command.json()["command_id"])

    def test_silent_toggle_marks_media_and_requeues_jobs(self):
        media_id = self.web.store.add_media(
            "clip", Path(self.tmp.name) / "clip.mp4", "clip.mp4", 1, "abc"
        )
        self.web.store.ensure_transcode_job(media_id, "generic_dlna")
        job = self.web.store.get_transcode(media_id, "generic_dlna")
        self.web.store.mark_job_done(job["id"], media_id, Path(self.tmp.name) / "clip.mp4")

        response = self.post(f"/api/v1/media/{media_id}/silent", {"silent": True})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["media"]["silent"])
        refreshed = self.web.store.get_transcode(media_id, "generic_dlna")
        self.assertEqual(refreshed["status"], "pending")

    def test_compression_toggle_marks_media_and_requeues_jobs(self):
        media_id = self.web.store.add_media(
            "clip", Path(self.tmp.name) / "clip.mp4", "clip.mp4", 1, "abc"
        )
        self.web.store.ensure_transcode_job(media_id, "generic_dlna")
        job = self.web.store.get_transcode(media_id, "generic_dlna")
        self.web.store.mark_job_done(job["id"], media_id, Path(self.tmp.name) / "clip.mp4")

        response = self.post(f"/api/v1/media/{media_id}/compressed", {"compressed": True})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["media"]["compressed"])
        refreshed = self.web.store.get_transcode(media_id, "generic_dlna")
        self.assertEqual(refreshed["status"], "pending")

    def test_operator_can_queue_mute_and_unmute(self):
        tv_response = self.post(
            "/api/v1/tvs",
            {"name": "MuteTV", "ip": "192.0.2.66", "profile": "generic_dlna"},
        )
        self.assertEqual(tv_response.status_code, 200, tv_response.text)
        tv_id = tv_response.json()["id"]

        mute = self.post(f"/api/v1/tvs/{tv_id}/commands", {"command": "mute"})
        unmute = self.post(f"/api/v1/tvs/{tv_id}/commands", {"command": "unmute"})

        self.assertEqual(mute.status_code, 200, mute.text)
        self.assertEqual(unmute.status_code, 200, unmute.text)
        self.assertTrue(mute.json()["command_id"])
        self.assertTrue(unmute.json()["command_id"])

    def test_deleting_tv_revokes_current_stream_ip(self):
        tv_response = self.post(
            "/api/v1/tvs",
            {"name": "DeleteTV", "ip": "192.0.2.77", "profile": "generic_dlna"},
        )
        self.assertEqual(tv_response.status_code, 200, tv_response.text)
        tv_id = tv_response.json()["id"]

        response = self.delete(f"/api/v1/tvs/{tv_id}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.web.stream_revoked("192.0.2.77"))
        self.assertIsNone(self.web.store.get_tv(tv_id))

    def test_tv_ip_must_match_allowed_cidr(self):
        response = self.post(
            "/api/v1/tvs",
            {"name": "Blocked", "ip": "198.51.100.55", "profile": "generic_dlna"},
        )

        self.assertEqual(response.status_code, 403)

    def test_viewer_cannot_mutate_operator_can_skip_not_admin_actions(self):
        viewer_id = self.web.store.create_user("viewer", "viewer-password-value", "viewer")
        operator_id = self.web.store.create_user("operator", "operator-password-value", "operator")
        self.assertTrue(viewer_id)
        self.assertTrue(operator_id)

        viewer = TestClient(self.web.app)
        viewer_login = viewer.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "viewer-password-value"},
        ).json()
        viewer_create = viewer.post(
            "/api/v1/playlists",
            json={"name": "Denied"},
            headers={"X-CSRF-Token": viewer_login["csrf_token"]},
        )

        operator = TestClient(self.web.app)
        operator_login = operator.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "operator-password-value"},
        ).json()
        operator_playlist = operator.post(
            "/api/v1/playlists",
            json={"name": "Operator Playlist"},
            headers={"X-CSRF-Token": operator_login["csrf_token"]},
        )
        original_save_upload = self.web.save_upload
        saved_upload_roles = []

        def fake_save_upload(file, user):
            saved_upload_roles.append(user["role"])
            target = Path(self.tmp.name) / "operator-upload.mp4"
            target.write_bytes(file.file.read() or b"video")
            return self.web.store.add_media(
                "operator-upload",
                target,
                "operator-upload.mp4",
                target.stat().st_size,
                "operator-upload-digest",
                duration_seconds=1,
            )

        self.web.save_upload = fake_save_upload
        try:
            viewer_upload = viewer.post(
                "/api/v1/media/upload",
                files={"file": ("viewer-upload.mp4", b"video", "video/mp4")},
                headers={"X-CSRF-Token": viewer_login["csrf_token"]},
            )
            operator_upload = operator.post(
                "/api/v1/media/upload",
                files={"file": ("operator-upload.mp4", b"video", "video/mp4")},
                headers={"X-CSRF-Token": operator_login["csrf_token"]},
            )
            operator_playlist_item = operator.post(
                f"/api/v1/playlists/{operator_playlist.json()['id']}/items",
                json={"media_id": operator_upload.json().get("id")},
                headers={"X-CSRF-Token": operator_login["csrf_token"]},
            )
        finally:
            self.web.save_upload = original_save_upload
        operator_user_list = operator.get("/api/v1/users")
        operator_diagnostics = operator.get("/api/v1/diagnostics")

        self.assertEqual(viewer_create.status_code, 403)
        self.assertEqual(viewer_upload.status_code, 403)
        self.assertEqual(operator_playlist.status_code, 200, operator_playlist.text)
        self.assertEqual(operator_upload.status_code, 200, operator_upload.text)
        self.assertEqual(operator_playlist_item.status_code, 200, operator_playlist_item.text)
        self.assertEqual(saved_upload_roles, ["operator"])
        self.assertEqual(operator_user_list.status_code, 403)
        self.assertEqual(operator_diagnostics.status_code, 403)

    def test_user_password_policy_allows_eight_characters(self):
        create = self.post(
            "/api/v1/users",
            {"username": "eight", "password": "abcdefgh", "role": "viewer"},
        )
        too_short = self.post(
            "/api/v1/users",
            {"username": "seven", "password": "abcdefg", "role": "viewer"},
        )

        self.assertEqual(create.status_code, 200, create.text)
        self.assertEqual(too_short.status_code, 400)
        self.assertIn("at least 8 characters", too_short.text)

    def test_user_management_and_password_change(self):
        create = self.post(
            "/api/v1/users",
            {"username": "alice", "password": "alice-password-value", "role": "viewer"},
        )
        self.assertEqual(create.status_code, 200, create.text)
        user_id = create.json()["id"]

        update = self.patch(f"/api/v1/users/{user_id}", {"role": "operator", "disabled": False})
        password = self.post(f"/api/v1/users/{user_id}/password", {"password": "new-password-value"})
        relogin = self.client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "new-password-value"},
        )

        self.assertEqual(update.status_code, 200, update.text)
        self.assertEqual(password.status_code, 200, password.text)
        self.assertEqual(relogin.status_code, 200, relogin.text)


if __name__ == "__main__":
    unittest.main()
