import importlib
import json
import os
import sys
import time
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

    def put(self, url: str, payload: dict):
        return self.client.put(url, json=payload, headers={"X-CSRF-Token": self.csrf})

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

    def test_node_enrollment_lifecycle(self):
        create = self.post("/api/v1/nodes", {"name": "Branch"})
        self.assertEqual(create.status_code, 200, create.text)
        enroll_token = create.json()["enroll_token"]
        node_id = create.json()["id"]

        bad = self.client.post("/api/v1/nodes/enroll", json={"enroll_token": "definitely-wrong-token"})
        self.assertEqual(bad.status_code, 403)

        enroll = self.client.post("/api/v1/nodes/enroll", json={"enroll_token": enroll_token})
        self.assertEqual(enroll.status_code, 200, enroll.text)
        node_token = enroll.json()["token"]
        self.assertEqual(enroll.json()["node_id"], node_id)

        again = self.client.post("/api/v1/nodes/enroll", json={"enroll_token": enroll_token})
        self.assertEqual(again.status_code, 403)

        nodes = self.client.get("/api/v1/nodes").json()["nodes"]
        self.assertEqual(len(nodes), 1)
        self.assertTrue(nodes[0]["enrolled"])

        media = self.client.get(
            "/api/v1/nodes/media/1/generic_dlna",
            headers={"X-Node-Token": node_token},
        )
        self.assertEqual(media.status_code, 404)
        unauthorized = self.client.get("/api/v1/nodes/media/1/generic_dlna")
        self.assertEqual(unauthorized.status_code, 401)

        delete = self.delete(f"/api/v1/nodes/{node_id}")
        self.assertEqual(delete.status_code, 200)
        revoked = self.client.get(
            "/api/v1/nodes/media/1/generic_dlna",
            headers={"X-Node-Token": node_token},
        )
        self.assertEqual(revoked.status_code, 401)

    def test_node_websocket_receives_config_and_reports_status(self):
        create = self.post("/api/v1/nodes", {"name": "Branch"})
        enroll_token = create.json()["enroll_token"]
        node_id = create.json()["id"]
        node_token = self.client.post("/api/v1/nodes/enroll", json={"enroll_token": enroll_token}).json()["token"]

        tv = self.post("/api/v1/tvs", {"name": "Remote TV", "ip": "10.99.0.5", "profile": "lg_webos", "node_id": node_id})
        self.assertEqual(tv.status_code, 200, tv.text)
        tv_id = tv.json()["id"]

        with self.client.websocket_connect(
            "/api/v1/nodes/ws",
            headers={"Authorization": f"Bearer {node_token}"},
        ) as websocket:
            config = json.loads(websocket.receive_text())
            self.assertEqual(config["type"], "tv_config")
            self.assertEqual([item["id"] for item in config["tvs"]], [tv_id])
            websocket.send_text(json.dumps({"type": "hello", "node_version": "2.0-test", "hostname": "branch-pi"}))
            websocket.send_text(
                json.dumps(
                    {
                        "type": "tv_status",
                        "tvs": [{"tv_id": tv_id, "online": True, "state": "PLAYING", "streaming": True, "current_media_id": None, "current_index": 0}],
                    }
                )
            )
            for _attempt in range(30):
                node = self.web.store.get_node(node_id)
                tv_row = self.web.store.get_tv(tv_id)
                if node.get("hostname") == "branch-pi" and tv_row.get("playback_state") == "PLAYING":
                    break
                time.sleep(0.1)
            self.assertEqual(node.get("hostname"), "branch-pi")
            self.assertEqual(tv_row.get("playback_state"), "PLAYING")
            self.assertTrue(self.web.node_hub.is_connected(node_id))

        # Disconnect marks the node offline and its TVs unreachable.
        for _attempt in range(30):
            tv_row = self.web.store.get_tv(tv_id)
            if not self.web.node_hub.is_connected(node_id) and tv_row.get("playback_state") == "OFFLINE":
                break
            time.sleep(0.1)
        self.assertFalse(self.web.node_hub.is_connected(node_id))
        self.assertEqual(tv_row.get("playback_state"), "OFFLINE")

    def test_node_tv_skips_local_allowlist_and_fails_commands_offline(self):
        outside_local = self.post("/api/v1/tvs", {"name": "Bad", "ip": "10.99.0.7", "profile": "generic_dlna"})
        self.assertEqual(outside_local.status_code, 403)

        create = self.post("/api/v1/nodes", {"name": "Branch"})
        node_id = create.json()["id"]
        tv = self.post("/api/v1/tvs", {"name": "Remote TV", "ip": "10.99.0.7", "profile": "generic_dlna", "node_id": node_id})
        self.assertEqual(tv.status_code, 200, tv.text)
        tv_id = tv.json()["id"]

        command = self.post(f"/api/v1/tvs/{tv_id}/commands", {"command": "stop"})
        self.assertEqual(command.status_code, 200, command.text)
        self.web.worker.process_tv_command()

        recent = self.web.store.recent_commands_for_tv(tv_id, 1)[0]
        self.assertEqual(recent["status"], "failed")
        self.assertIn("offline", recent["error"].lower())

    def test_api_docs_can_be_disabled(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)

        os.environ["SCREENLOOP_API_DOCS"] = "false"
        try:
            for name in list(sys.modules):
                if name == "screenloop" or name.startswith("screenloop."):
                    sys.modules.pop(name, None)
            web = importlib.import_module("screenloop.web")
            client = TestClient(web.app)
            self.assertEqual(client.get("/docs").status_code, 404)
            self.assertEqual(client.get("/openapi.json").status_code, 404)
        finally:
            os.environ.pop("SCREENLOOP_API_DOCS", None)

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

    def make_group(self, name, parent_id=None):
        response = self.post("/api/v1/groups", {"name": name, "parent_id": parent_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def test_group_custom_schedule_round_trips(self):
        response = self.post(
            "/api/v1/groups",
            {
                "name": "Night shift",
                "schedule_mode": "custom",
                "schedule_days": "0,1,2,3,4",
                "schedule_start": "22:00",
                "schedule_end": "06:00",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        group = response.json()["group"]
        self.assertEqual(group["schedule_mode"], "custom")
        self.assertEqual(group["schedule_days"], "0,1,2,3,4")
        self.assertEqual(group["schedule_start"], "22:00")
        self.assertEqual(group["schedule_end"], "06:00")
        listed = self.client.get("/api/v1/groups").json()["groups"]
        listed_group = next(item for item in listed if item["id"] == group["id"])
        self.assertEqual(listed_group.get("schedule_mode"), "custom")
        self.assertEqual(listed_group.get("schedule_start"), "22:00")

    def test_group_rename_preserves_schedule(self):
        group_id = self.make_group("Before")
        configured = self.patch(
            f"/api/v1/groups/{group_id}",
            {
                "schedule_mode": "custom",
                "schedule_days": "0",
                "schedule_start": "09:00",
                "schedule_end": "17:00",
            },
        )
        self.assertEqual(configured.status_code, 200, configured.text)

        renamed = self.patch(f"/api/v1/groups/{group_id}", {"name": "After"})

        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["group"]["schedule_start"], "09:00")

    def test_invalid_group_schedule_does_not_apply_rename(self):
        group_id = self.make_group("Stable")

        response = self.patch(
            f"/api/v1/groups/{group_id}",
            {
                "name": "Partial",
                "schedule_mode": "custom",
                "schedule_days": "0",
                "schedule_start": "bad",
                "schedule_end": "17:00",
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.web.store.get_group(group_id)["name"], "Stable")

    def test_noncustom_group_mode_clears_stale_window(self):
        group_id = self.make_group("Clear me")
        self.patch(
            f"/api/v1/groups/{group_id}",
            {
                "schedule_mode": "custom",
                "schedule_days": "0",
                "schedule_start": "09:00",
                "schedule_end": "17:00",
            },
        )

        response = self.patch(f"/api/v1/groups/{group_id}", {"schedule_mode": "always"})

        self.assertEqual(response.status_code, 200, response.text)
        group = response.json()["group"]
        self.assertEqual(group["schedule_mode"], "always")
        self.assertIsNone(group["schedule_days"])
        self.assertIsNone(group["schedule_start"])
        self.assertIsNone(group["schedule_end"])

    def test_group_tree_crud_and_tv_assignment(self):
        org = self.make_group("Организация")
        branch = self.make_group("Филиал", org)

        listed = self.client.get("/api/v1/groups").json()["groups"]
        self.assertEqual([g["name"] for g in listed], ["Организация", "Филиал"])
        self.assertEqual(listed[1]["depth"], 1)
        self.assertEqual(listed[1]["path"], "Организация / Филиал")

        created = self.post("/api/v1/tvs", {"name": "Холл", "ip": "192.0.2.50", "group_id": branch})
        self.assertEqual(created.status_code, 200, created.text)
        tv_id = created.json()["id"]
        self.assertEqual(self.web.store.get_tv(tv_id)["group_id"], branch)

        moved = self.patch(
            f"/api/v1/tvs/{tv_id}",
            {"name": "Холл", "ip": "192.0.2.50", "profile": "generic_dlna", "group_id": org},
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(self.web.store.get_tv(tv_id)["group_id"], org)

    def test_group_cannot_be_moved_into_its_own_descendant(self):
        org = self.make_group("Организация")
        branch = self.make_group("Филиал", org)
        floor = self.make_group("Этаж", branch)

        response = self.patch(f"/api/v1/groups/{org}", {"parent_id": floor, "move": True})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("inside itself", response.json()["detail"])
        self.assertIsNone(self.web.store.get_group(org)["parent_id"])

    def test_duplicate_group_name_under_the_same_parent_is_rejected(self):
        org = self.make_group("Организация")
        self.make_group("Филиал", org)

        duplicate = self.post("/api/v1/groups", {"name": "Филиал", "parent_id": org})
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        duplicate_root = self.post("/api/v1/groups", {"name": "Организация"})
        self.assertEqual(duplicate_root.status_code, 409, duplicate_root.text)

    def test_group_nesting_depth_is_capped(self):
        parent = None
        for level in range(self.web.store.MAX_GROUP_DEPTH):
            parent = self.make_group(f"level-{level}", parent)

        too_deep = self.post("/api/v1/groups", {"name": "overflow", "parent_id": parent})

        self.assertEqual(too_deep.status_code, 400, too_deep.text)
        self.assertIn("deeper than", too_deep.json()["detail"])

    def test_deleting_a_group_keeps_its_tvs(self):
        org = self.make_group("Организация")
        branch = self.make_group("Филиал", org)
        tv_id = self.post("/api/v1/tvs", {"name": "Холл", "ip": "192.0.2.51", "group_id": branch}).json()["id"]

        response = self.delete(f"/api/v1/groups/{org}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["removed"], 2)
        self.assertIsNotNone(self.web.store.get_tv(tv_id))
        self.assertIsNone(self.web.store.get_tv(tv_id)["group_id"])

    def test_unknown_group_is_rejected_on_tv_create(self):
        response = self.post("/api/v1/tvs", {"name": "Холл", "ip": "192.0.2.52", "group_id": 9999})

        self.assertEqual(response.status_code, 404, response.text)
        self.assertIsNone(self.web.store.get_tv_by_ip("192.0.2.52"))

    def test_unknown_group_is_rejected_before_tv_update(self):
        group_id = self.make_group("Организация")
        tv_id = self.post(
            "/api/v1/tvs",
            {"name": "Холл", "ip": "192.0.2.53", "group_id": group_id},
        ).json()["id"]

        response = self.patch(
            f"/api/v1/tvs/{tv_id}",
            {"name": "Изменён", "ip": "192.0.2.54", "profile": "generic_dlna", "group_id": 9999},
        )

        self.assertEqual(response.status_code, 404, response.text)
        tv = self.web.store.get_tv(tv_id)
        self.assertEqual(tv["name"], "Холл")
        self.assertEqual(tv["ip"], "192.0.2.53")
        self.assertEqual(tv["group_id"], group_id)

    def test_moving_a_branch_cannot_push_descendants_past_max_depth(self):
        moving = self.make_group("moving")
        child = self.make_group("moving-child", moving)
        parent = None
        for level in range(self.web.store.MAX_GROUP_DEPTH - 1):
            parent = self.make_group(f"target-{level}", parent)

        response = self.patch(f"/api/v1/groups/{moving}", {"parent_id": parent, "move": True})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIsNone(self.web.store.get_group(moving)["parent_id"])
        self.assertEqual(self.web.store.get_group(child)["parent_id"], moving)

    def test_failed_group_rename_and_move_is_atomic(self):
        moving = self.make_group("Исходная")
        target = self.make_group("Назначение")
        self.make_group("Занято", target)

        response = self.patch(
            f"/api/v1/groups/{moving}",
            {"name": "Занято", "parent_id": target, "move": True},
        )

        self.assertEqual(response.status_code, 409, response.text)
        group = self.web.store.get_group(moving)
        self.assertEqual(group["name"], "Исходная")
        self.assertIsNone(group["parent_id"])

    def test_group_mutations_are_admin_only_but_listing_is_not(self):
        self.web.store.create_user("viewer", "viewer-password-value", "viewer")
        viewer = TestClient(self.web.app)
        token = viewer.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "viewer-password-value"},
        ).json()["csrf_token"]

        self.assertEqual(viewer.get("/api/v1/groups").status_code, 200)
        self.assertEqual(
            viewer.post("/api/v1/groups", json={"name": "Свои"}, headers={"X-CSRF-Token": token}).status_code,
            403,
        )

    SONY_TEMPLATE = (
        b'name = "Sony Bravia"\n'
        b'match = ["sony", "bravia"]\n\n'
        b"[ffmpeg]\n"
        b'video_codec = "libx264"\n'
        b'audio_codec = "aac"\n'
        b"max_width = 1920\n"
        b"max_height = 1080\n"
        b"fps = 30\n"
        b"crf = 22\n"
        b'maxrate = "12000k"\n'
        b'bufsize = "24000k"\n'
        b'audio_bitrate = "160k"\n'
    )

    def upload_template(self, filename: str, body: bytes):
        return self.client.post(
            "/api/v1/profiles/upload",
            files={"file": (filename, body, "application/toml")},
            headers={"X-CSRF-Token": self.csrf},
        )

    def test_profiles_list_marks_builtin_and_custom(self):
        response = self.client.get("/api/v1/profiles")

        self.assertEqual(response.status_code, 200, response.text)
        profiles = {item["id"]: item for item in response.json()["profiles"]}
        self.assertEqual(profiles["generic_dlna"]["source"], "builtin")
        self.assertEqual(profiles["samsung_legacy"]["name"], "Samsung Legacy Smart TV")

        self.assertEqual(self.upload_template("sony_bravia.toml", self.SONY_TEMPLATE).status_code, 200)
        listed = {item["id"]: item for item in self.client.get("/api/v1/profiles").json()["profiles"]}
        self.assertEqual(listed["sony_bravia"]["source"], "custom")
        self.assertEqual(listed["sony_bravia"]["name"], "Sony Bravia")

    def test_profile_upload_installs_and_reloads_without_restart(self):
        self.assertNotIn("sony_bravia", self.web.PROFILES)

        response = self.upload_template("sony_bravia.toml", self.SONY_TEMPLATE)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["profile"]["id"], "sony_bravia")
        self.assertIn("sony_bravia", self.web.PROFILES)
        self.assertTrue((self.web.config.PROFILES_DIR / "sony_bravia.toml").is_file())
        events = [event["event_type"] for event in self.web.store.list_events()]
        self.assertIn("profile_installed", events)

    def test_profile_install_by_url_validates_before_writing(self):
        calls = {}

        def fake_fetch(url, timeout=10):
            calls["url"] = url
            return self.SONY_TEMPLATE

        original = self.web.fetch_template
        self.web.fetch_template = fake_fetch
        try:
            response = self.post(
                "/api/v1/profiles/install",
                {"url": "https://example.test/templates/sony_bravia.toml"},
            )
        finally:
            self.web.fetch_template = original

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(calls["url"], "https://example.test/templates/sony_bravia.toml")
        self.assertEqual(response.json()["profile"]["id"], "sony_bravia")
        self.assertIn("sony_bravia", self.web.PROFILES)

    def test_profile_install_rejects_non_http_scheme(self):
        response = self.post("/api/v1/profiles/install", {"url": "file:///etc/passwd"})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("unsupported URL scheme", json.dumps(response.json()))

    def test_broken_template_is_rejected_with_field_errors(self):
        broken = self.SONY_TEMPLATE.replace(b"crf = 22\n", b"crf = 99\n").replace(b"fps = 30\n", b"")

        response = self.upload_template("sony_bravia.toml", broken)

        self.assertEqual(response.status_code, 400, response.text)
        errors = response.json()["detail"]["errors"]
        self.assertIn("ffmpeg.fps is required", errors)
        self.assertIn("ffmpeg.crf must be between 0 and 51", errors)
        self.assertNotIn("sony_bravia", self.web.PROFILES)
        self.assertFalse((self.web.config.PROFILES_DIR / "sony_bravia.toml").exists())

    def test_template_id_cannot_traverse_out_of_the_profiles_dir(self):
        response = self.upload_template("../../evil.toml", self.SONY_TEMPLATE)

        # UploadFile names are basenamed first, so this lands as "evil" and is
        # accepted; the traversal attempt must never write outside PROFILES_DIR.
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue((self.web.config.PROFILES_DIR / "evil.toml").is_file())
        self.assertFalse((Path(self.tmp.name).parent / "evil.toml").exists())

        bad = self.post("/api/v1/profiles/install", {"url": "https://x.test/a.toml", "profile_id": "../evil"})
        self.assertEqual(bad.status_code, 400, bad.text)

    def test_builtin_template_cannot_be_replaced_or_deleted(self):
        upload = self.upload_template("lg_webos.toml", self.SONY_TEMPLATE)

        self.assertEqual(upload.status_code, 400, upload.text)
        self.assertIn("built-in", json.dumps(upload.json()))
        self.assertEqual(self.web.PROFILES["lg_webos"]["name"], "LG webOS")

        deleted = self.delete("/api/v1/profiles/lg_webos")
        self.assertEqual(deleted.status_code, 400, deleted.text)
        self.assertIn("lg_webos", self.web.PROFILES)

    def test_custom_template_delete_is_blocked_while_assigned_to_a_tv(self):
        self.assertEqual(self.upload_template("sony_bravia.toml", self.SONY_TEMPLATE).status_code, 200)
        self.post("/api/v1/tvs", {"name": "Lobby", "ip": "192.0.2.40", "profile": "sony_bravia"})

        blocked = self.delete("/api/v1/profiles/sony_bravia")

        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("Lobby", blocked.json()["detail"])
        self.assertIn("sony_bravia", self.web.PROFILES)

    def test_unassigned_custom_template_can_be_deleted(self):
        self.assertEqual(self.upload_template("sony_bravia.toml", self.SONY_TEMPLATE).status_code, 200)

        response = self.delete("/api/v1/profiles/sony_bravia")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("sony_bravia", self.web.PROFILES)
        self.assertFalse((self.web.config.PROFILES_DIR / "sony_bravia.toml").exists())
        self.assertEqual(self.delete("/api/v1/profiles/sony_bravia").status_code, 404)
        events = [event["event_type"] for event in self.web.store.list_events()]
        self.assertIn("profile_deleted", events)

    def test_profile_routes_are_admin_only(self):
        self.web.store.create_user("operator", "operator-password-value", "operator")
        operator = TestClient(self.web.app)
        token = operator.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "operator-password-value"},
        ).json()["csrf_token"]
        headers = {"X-CSRF-Token": token}

        self.assertEqual(operator.get("/api/v1/profiles").status_code, 403)
        self.assertEqual(operator.post("/api/v1/profiles/install", json={"url": "https://x.test/a.toml"}, headers=headers).status_code, 403)
        self.assertEqual(operator.delete("/api/v1/profiles/sony_bravia", headers=headers).status_code, 403)
        self.assertEqual(
            operator.post(
                "/api/v1/profiles/upload",
                files={"file": ("sony_bravia.toml", self.SONY_TEMPLATE, "application/toml")},
                headers=headers,
            ).status_code,
            403,
        )

    def test_catalog_is_off_by_default_and_makes_no_network_call(self):
        calls = []
        original = self.web.urllib.request.urlopen
        self.web.urllib.request.urlopen = lambda *args, **kwargs: calls.append(args) or original(*args, **kwargs)
        try:
            response = self.client.get("/api/v1/profiles/catalog")
        finally:
            self.web.urllib.request.urlopen = original

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["enabled"])
        self.assertEqual(response.json()["entries"], [])
        self.assertEqual(calls, [])

        blocked = self.post("/api/v1/profiles/install", {"catalog_id": "sony_bravia"})
        self.assertEqual(blocked.status_code, 400, blocked.text)
        self.assertIn("disabled", blocked.json()["detail"])

    def enable_catalog(self, entries):
        self.web.config.COMMUNITY_CATALOG_CHECK = True
        self.web._catalog_cache.update({"checked_at": time.time(), "entries": entries, "error": None})
        self.addCleanup(setattr, self.web.config, "COMMUNITY_CATALOG_CHECK", False)
        self.addCleanup(self.web._catalog_cache.update, {"checked_at": 0, "entries": [], "error": None})

    def test_catalog_lists_entries_and_marks_installed_ones(self):
        self.enable_catalog(
            [
                {
                    "id": "sony_bravia",
                    "name": "Sony Bravia",
                    "vendor": "Sony",
                    "author": "someone",
                    "description": "",
                    "url": "https://example.test/templates/sony_bravia.toml",
                }
            ]
        )

        listed = self.client.get("/api/v1/profiles/catalog").json()
        self.assertTrue(listed["enabled"])
        self.assertFalse(listed["entries"][0]["installed"])

        self.assertEqual(self.upload_template("sony_bravia.toml", self.SONY_TEMPLATE).status_code, 200)
        self.assertTrue(self.client.get("/api/v1/profiles/catalog").json()["entries"][0]["installed"])

    def test_install_from_catalog_resolves_the_entry_url(self):
        self.enable_catalog(
            [{"id": "sony_bravia", "name": "Sony Bravia", "vendor": "", "author": "", "description": "", "url": "https://example.test/templates/sony_bravia.toml"}]
        )
        fetched = {}

        def fake_fetch(url, timeout=10):
            fetched["url"] = url
            return self.SONY_TEMPLATE

        original = self.web.fetch_template
        self.web.fetch_template = fake_fetch
        try:
            response = self.post("/api/v1/profiles/install", {"catalog_id": "sony_bravia"})
        finally:
            self.web.fetch_template = original

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(fetched["url"], "https://example.test/templates/sony_bravia.toml")
        self.assertIn("sony_bravia", self.web.PROFILES)

        missing = self.post("/api/v1/profiles/install", {"catalog_id": "nothing_here"})
        self.assertEqual(missing.status_code, 404, missing.text)

    def test_catalog_index_is_normalized_and_relative_files_resolved(self):
        entries = self.web.parse_catalog(
            {
                "templates": [
                    {"id": "sony_bravia", "name": "Sony Bravia", "file": "templates/sony_bravia.toml"},
                    {"id": "philips", "vendor": "Philips"},
                    {"name": "no id"},
                    "garbage",
                ]
            }
        )

        self.assertEqual([entry["id"] for entry in entries], ["sony_bravia", "philips"])
        self.assertTrue(entries[0]["url"].endswith("/templates/sony_bravia.toml"))
        self.assertTrue(entries[1]["url"].endswith("/templates/philips.toml"))
        self.assertEqual(entries[1]["name"], "philips")

    def test_custom_template_reaches_nodes_in_tv_config(self):
        self.assertEqual(self.upload_template("sony_bravia.toml", self.SONY_TEMPLATE).status_code, 200)
        node_id = self.post("/api/v1/nodes", {"name": "branch"}).json()["id"]
        self.post("/api/v1/tvs", {"name": "Lobby", "ip": "192.0.2.41", "profile": "sony_bravia", "node_id": node_id})

        message = self.web.node_tv_config_message(node_id)

        self.assertIn("sony_bravia", message["profiles"])
        self.assertEqual(message["tvs"][0]["profile"], "sony_bravia")

    def test_upload_queues_transcode_jobs_only_for_profiles_in_use(self):
        # With no TVs configured only the fallback profile is worth transcoding.
        self.assertEqual(self.web.profiles_in_use(), ["generic_dlna"])

        self.post("/api/v1/tvs", {"name": "TV", "ip": "192.0.2.30", "profile": "samsung_legacy"})

        self.assertEqual(self.web.profiles_in_use(), ["generic_dlna", "samsung_legacy"])
        self.assertNotIn("lg_webos", self.web.profiles_in_use())

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
        without_confirmation = self.post(f"/api/v1/users/{user_id}/password", {"password": "new-password-value"})
        wrong_confirmation = self.post(
            f"/api/v1/users/{user_id}/password",
            {"password": "new-password-value", "admin_password": "not-my-password"},
        )
        password = self.post(
            f"/api/v1/users/{user_id}/password",
            {"password": "new-password-value", "admin_password": TEST_ADMIN_PASSWORD},
        )
        relogin = self.client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "new-password-value"},
        )

        self.assertEqual(update.status_code, 200, update.text)
        self.assertEqual(without_confirmation.status_code, 422)
        self.assertEqual(wrong_confirmation.status_code, 403)
        self.assertEqual(password.status_code, 200, password.text)
        self.assertEqual(relogin.status_code, 200, relogin.text)

    def test_self_password_change_keeps_current_session(self):
        create = self.post(
            "/api/v1/users",
            {"username": "bob", "password": "bob-first-password", "role": "operator"},
        )
        self.assertEqual(create.status_code, 200, create.text)

        bob = TestClient(self.web.app)
        bob_login = bob.post("/api/v1/auth/login", json={"username": "bob", "password": "bob-first-password"})
        self.assertEqual(bob_login.status_code, 200, bob_login.text)
        bob_csrf = bob_login.json()["csrf_token"]

        bob_other = TestClient(self.web.app)
        other_login = bob_other.post("/api/v1/auth/login", json={"username": "bob", "password": "bob-first-password"})
        self.assertEqual(other_login.status_code, 200)

        wrong_current = bob.post(
            "/api/v1/me/password",
            json={"current_password": "not-the-password", "new_password": "bob-second-password"},
            headers={"X-CSRF-Token": bob_csrf},
        )
        changed = bob.post(
            "/api/v1/me/password",
            json={"current_password": "bob-first-password", "new_password": "bob-second-password"},
            headers={"X-CSRF-Token": bob_csrf},
        )

        self.assertEqual(wrong_current.status_code, 403)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(bob.get("/api/v1/session").status_code, 200)
        self.assertEqual(bob_other.get("/api/v1/session").status_code, 401)
        relogin = self.client.post("/api/v1/auth/login", json={"username": "bob", "password": "bob-second-password"})
        self.assertEqual(relogin.status_code, 200)

    def test_last_admin_cannot_be_demoted_or_disabled(self):
        me = self.client.get("/api/v1/session").json()["user"]

        demote = self.patch(f"/api/v1/users/{me['id']}", {"role": "viewer", "disabled": False})
        self.assertEqual(demote.status_code, 400)
        self.assertIn("last active admin", demote.text)

        create = self.post(
            "/api/v1/users",
            {"username": "second-admin", "password": "second-admin-pass", "role": "admin"},
        )
        self.assertEqual(create.status_code, 200, create.text)
        demote_now = self.patch(f"/api/v1/users/{me['id']}", {"role": "viewer", "disabled": False})
        self.assertEqual(demote_now.status_code, 200, demote_now.text)

    def test_own_sessions_listing_and_revocation(self):
        other = TestClient(self.web.app)
        other_login = other.post("/api/v1/auth/login", json={"username": "admin", "password": TEST_ADMIN_PASSWORD})
        self.assertEqual(other_login.status_code, 200)

        sessions = self.client.get("/api/v1/me/sessions").json()["sessions"]
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sum(1 for item in sessions if item["current"]), 1)

        removed = self.delete("/api/v1/me/sessions").json()
        self.assertEqual(removed["removed"], 1)
        self.assertEqual(self.client.get("/api/v1/session").status_code, 200)
        self.assertEqual(other.get("/api/v1/session").status_code, 401)

    def test_viewer_does_not_see_security_events(self):
        create = self.post(
            "/api/v1/users",
            {"username": "watcher", "password": "watcher-password", "role": "viewer"},
        )
        self.assertEqual(create.status_code, 200, create.text)
        self.web.store.add_event(None, "tv_stop", "Stop sent")

        viewer = TestClient(self.web.app)
        viewer_login = viewer.post("/api/v1/auth/login", json={"username": "watcher", "password": "watcher-password"})
        self.assertEqual(viewer_login.status_code, 200)

        viewer_events = viewer.get("/api/v1/events").json()["events"]
        admin_events = self.client.get("/api/v1/events").json()["events"]

        viewer_types = {event["event_type"] for event in viewer_events}
        admin_types = {event["event_type"] for event in admin_events}
        self.assertIn("tv_stop", viewer_types)
        self.assertFalse(any(t.startswith(("login", "user", "security")) for t in viewer_types))
        self.assertIn("login_success", admin_types)

    def test_login_rate_limited_per_username(self):
        for _index in range(10):
            self.web.record_failure(self.web._auth_failures, "user:brute-target")

        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "Brute-Target", "password": "whatever-password"},
        )

        self.assertEqual(response.status_code, 429)

    # --- upload defaults ------------------------------------------------

    def test_media_defaults_start_off(self):
        """An upgrade must keep producing exactly what it produced before."""
        response = self.client.get("/api/v1/settings/media")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["defaults"], {"silent": False, "compressed": False})

    def test_admin_can_change_media_defaults(self):
        saved = self.put("/api/v1/settings/media", {"silent": True, "compressed": True})

        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(
            self.client.get("/api/v1/settings/media").json()["defaults"],
            {"silent": True, "compressed": True},
        )

    def test_a_new_upload_inherits_the_defaults(self):
        self.put("/api/v1/settings/media", {"silent": True, "compressed": False})

        media_id = self.web.store.add_media(
            "clip",
            Path(self.tmp.name) / "clip.mp4",
            "clip.mp4",
            10,
            "digest",
            5,
            **self.web.store.get_media_defaults(),
        )

        media = self.web.store.get_media(media_id)
        self.assertTrue(media["silent"])
        self.assertFalse(media["compressed"])

    def test_viewers_cannot_change_media_defaults(self):
        self.post("/api/v1/users", {"username": "looker", "password": TEST_ADMIN_PASSWORD, "role": "viewer"})
        viewer = TestClient(self.web.app)
        csrf = viewer.post(
            "/api/v1/auth/login",
            json={"username": "looker", "password": TEST_ADMIN_PASSWORD},
        ).json()["csrf_token"]

        response = viewer.put(
            "/api/v1/settings/media",
            json={"silent": True, "compressed": True},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(response.status_code, 403)

    # --- operating hours ------------------------------------------------

    def test_schedule_is_disabled_by_default(self):
        response = self.client.get("/api/v1/schedule")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["schedule"]["enabled"])
        self.assertTrue(body["open"], "playback must be unrestricted until a schedule is set")

    def test_schedule_requires_auth(self):
        anonymous = TestClient(self.web.app)
        self.assertEqual(anonymous.get("/api/v1/schedule").status_code, 401)

    def test_admin_can_set_the_schedule(self):
        response = self.put(
            "/api/v1/schedule",
            {"enabled": True, "days": "0,1,2,3,4", "start": "08:00", "end": "20:00"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.client.get("/api/v1/schedule").json()["schedule"],
            {"enabled": True, "days": "0,1,2,3,4", "start": "08:00", "end": "20:00"},
        )

    def test_schedule_rejects_an_unusable_window(self):
        for payload in [
            {"enabled": True, "days": "0", "start": "aa:bb", "end": "20:00"},
            {"enabled": True, "days": "0", "start": "08:00", "end": "08:00"},
            {"enabled": True, "days": "9", "start": "08:00", "end": "20:00"},
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(self.put("/api/v1/schedule", payload).status_code, 400)

    def test_operators_cannot_change_the_schedule(self):
        self.post(
            "/api/v1/users",
            {"username": "opie", "password": TEST_ADMIN_PASSWORD, "role": "operator"},
        )
        operator = TestClient(self.web.app)
        csrf = operator.post(
            "/api/v1/auth/login",
            json={"username": "opie", "password": TEST_ADMIN_PASSWORD},
        ).json()["csrf_token"]

        response = operator.put(
            "/api/v1/schedule",
            json={"enabled": True, "days": "0", "start": "08:00", "end": "20:00"},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(response.status_code, 403)

    def test_tv_can_carry_its_own_window(self):
        tv_id = self.post("/api/v1/tvs", {"name": "Hall", "ip": "192.0.2.71"}).json()["id"]

        response = self.patch(
            f"/api/v1/tvs/{tv_id}",
            {
                "name": "Hall",
                "ip": "192.0.2.71",
                "profile": "generic_dlna",
                "schedule_mode": "custom",
                "schedule_days": "0,1,2,3,4,5,6",
                "schedule_start": "09:00",
                "schedule_end": "22:00",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        tv = response.json()["tv"]
        self.assertEqual(tv["schedule_mode"], "custom")
        self.assertEqual(tv["schedule_start"], "09:00")
        self.assertEqual(tv["schedule_end"], "22:00")

    def test_tv_schedule_is_validated(self):
        tv_id = self.post("/api/v1/tvs", {"name": "Hall", "ip": "192.0.2.72"}).json()["id"]
        base = {"name": "Hall", "ip": "192.0.2.72", "profile": "generic_dlna"}

        bad_mode = self.patch(f"/api/v1/tvs/{tv_id}", {**base, "schedule_mode": "whenever"})
        bad_time = self.patch(
            f"/api/v1/tvs/{tv_id}",
            {**base, "schedule_mode": "custom", "schedule_days": "0", "schedule_start": "9", "schedule_end": "22:00"},
        )

        self.assertEqual(bad_mode.status_code, 400)
        self.assertEqual(bad_time.status_code, 400)

    def test_resume_clears_a_suspension(self):
        tv_id = self.post("/api/v1/tvs", {"name": "Hall", "ip": "192.0.2.73"}).json()["id"]
        self.web.store.suspend_tv_playback(tv_id, "renderer_reset")

        first = self.post(f"/api/v1/tvs/{tv_id}/resume")
        second = self.post(f"/api/v1/tvs/{tv_id}/resume")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["resumed"])
        self.assertIsNone(first.json()["tv"]["playback_suspended_at"])
        self.assertFalse(second.json()["resumed"], "resuming twice must be a no-op")

    def test_status_says_why_a_screen_is_dark(self):
        tv_id = self.post("/api/v1/tvs", {"name": "Hall", "ip": "192.0.2.74"}).json()["id"]
        self.web.store.suspend_tv_playback(tv_id, "renderer_reset")

        tv = next(tv for tv in self.client.get("/api/v1/status").json()["tvs"] if tv["id"] == tv_id)

        self.assertTrue(tv["playback_suspended"])
        self.assertIn("schedule_open", tv)


if __name__ == "__main__":
    unittest.main()
