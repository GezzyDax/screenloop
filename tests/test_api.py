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
                "SCREENLOOP_BOOTSTRAP_PASSWORD": "test-password-please-change",
                "SCREENLOOP_SECRET_KEY": "test-secret-please-change",
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
        self.web.store.ensure_bootstrap_admin("admin", "test-password-please-change")
        self.client = TestClient(self.web.app)
        self.csrf = self.login("admin", "test-password-please-change")["csrf_token"]

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

        self.assertEqual(session.status_code, 200)
        self.assertEqual(session.json()["user"]["role"], "admin")
        self.assertIn("csrf_token", session.json())
        self.assertEqual(status.status_code, 200)
        self.assertIn("tvs", status.json())

    def test_unsafe_api_requires_csrf(self):
        response = self.client.post("/api/v1/playlists", json={"name": "No CSRF"})

        self.assertEqual(response.status_code, 403)

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
        operator_user_list = operator.get("/api/v1/users")

        self.assertEqual(viewer_create.status_code, 403)
        self.assertEqual(operator_playlist.status_code, 200, operator_playlist.text)
        self.assertEqual(operator_user_list.status_code, 403)

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
