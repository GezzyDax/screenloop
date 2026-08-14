"""Authorisation over HTTP: unchanged access, and no route to more of it.

Making permissions composable removed the old guarantee that anybody who could
reach an administrative endpoint was already all-powerful. These tests exist to
prove that removing it did not open a door.
"""

import importlib
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from screenloop import permissions

TEST_ADMIN_PASSWORD = "test-admin-password"
TEST_SECRET_KEY = "test-secret-key-that-is-long-enough-0123456789"


class AuthzTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
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
        self.web.store.ensure_bootstrap_admin("admin", TEST_ADMIN_PASSWORD)
        self.store = self.web.store
        self.client = TestClient(self.web.app)
        self.csrf = self.login(self.client, "admin", TEST_ADMIN_PASSWORD)

    def login(self, client: TestClient, username: str, password: str) -> str:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["csrf_token"]

    def as_user(self, username: str, granted: frozenset[str]) -> tuple[TestClient, str]:
        """A user holding exactly `granted`, via a custom role."""
        user_id = self.store.create_user(username, TEST_ADMIN_PASSWORD, "viewer")
        role_id = self.store.create_role(f"role-{username}", "", granted)
        self.store.set_user_roles(user_id, [{"role_id": role_id, "scope_type": "global", "scope_id": None}])
        client = TestClient(self.web.app)
        return client, self.login(client, username, TEST_ADMIN_PASSWORD)

    def post(self, url, payload=None, client=None, csrf=None):
        client = client or self.client
        return client.post(url, json=payload or {}, headers={"X-CSRF-Token": csrf or self.csrf})

    def patch(self, url, payload, client=None, csrf=None):
        client = client or self.client
        return client.patch(url, json=payload, headers={"X-CSRF-Token": csrf or self.csrf})

    def put(self, url, payload, client=None, csrf=None):
        client = client or self.client
        return client.put(url, json=payload, headers={"X-CSRF-Token": csrf or self.csrf})

    def delete(self, url, client=None, csrf=None):
        client = client or self.client
        return client.delete(url, headers={"X-CSRF-Token": csrf or self.csrf})


class SessionShapeTests(AuthzTestCase):
    def test_session_reports_what_the_caller_may_do(self):
        body = self.client.get("/api/v1/session").json()
        self.assertEqual(frozenset(body["permissions"]), permissions.KEYS)
        self.assertEqual(frozenset(body["user"]["permissions"]), permissions.KEYS)

    def test_a_custom_role_reports_only_its_own_permissions(self):
        client, _ = self.as_user("narrow", frozenset({"tv.view"}))
        self.assertEqual(client.get("/api/v1/session").json()["permissions"], ["tv.view"])


class LoginPayloadTests(AuthzTestCase):
    def test_login_reports_permissions_without_a_second_call(self):
        """The panel renders from this response; an empty set hides everything."""
        client = TestClient(self.web.app)
        body = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
        ).json()

        self.assertEqual(frozenset(body["permissions"]), permissions.KEYS)
        self.assertEqual(frozenset(body["user"]["permissions"]), permissions.KEYS)

    def test_login_and_session_agree(self):
        client = TestClient(self.web.app)
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
        ).json()
        session = client.get("/api/v1/session").json()

        self.assertEqual(login["permissions"], session["permissions"])


class GateTests(AuthzTestCase):
    def test_a_permission_grants_exactly_its_own_endpoint(self):
        client, csrf = self.as_user("viewer-only", frozenset({"tv.view"}))

        self.assertEqual(client.get("/api/v1/tvs").status_code, 200)
        self.assertEqual(client.get("/api/v1/media").status_code, 403)
        self.assertEqual(client.get("/api/v1/roles").status_code, 403)

    def test_revoking_a_role_takes_effect_on_the_next_request(self):
        """Permissions are read per request, not cached into the session."""
        client, _ = self.as_user("fleeting", frozenset({"tv.view"}))
        self.assertEqual(client.get("/api/v1/tvs").status_code, 200)

        user = self.store.get_user_by_username("fleeting")
        self.store.set_user_roles(int(user["id"]), [])

        self.assertEqual(client.get("/api/v1/tvs").status_code, 403)

    def test_a_denial_is_written_to_the_audit_log(self):
        client, _ = self.as_user("denied", frozenset({"tv.view"}))
        client.get("/api/v1/roles")

        denials = self.store.list_events(None, "security_denied", 5)

        self.assertTrue(denials)
        self.assertIn("role.manage", denials[0]["details"])

    def test_rediscover_needs_device_management_not_playback(self):
        tv_id = self.post("/api/v1/tvs", {"name": "Hall", "ip": "192.0.2.80"}).json()["id"]
        client, csrf = self.as_user("commander", frozenset({"tv.view", "tv.command"}))

        allowed = self.post(f"/api/v1/tvs/{tv_id}/commands", {"command": "stop"}, client, csrf)
        refused = self.post(f"/api/v1/tvs/{tv_id}/commands", {"command": "rediscover"}, client, csrf)

        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(refused.status_code, 403)

    def test_security_events_need_their_own_permission(self):
        plain, _ = self.as_user("plain", frozenset({"event.view"}))
        cleared, _ = self.as_user("cleared", frozenset({"event.view", "event.security.view"}))

        plain_types = {event["event_type"] for event in plain.get("/api/v1/events").json()["events"]}
        cleared_types = {event["event_type"] for event in cleared.get("/api/v1/events").json()["events"]}

        self.assertFalse(any(t.startswith(("login", "security", "user", "logout")) for t in plain_types))
        self.assertTrue(any(t.startswith("login") for t in cleared_types))

    def test_tv_reads_do_not_expose_internal_group_schedule_chains(self):
        group_id = self.store.create_group(
            "Restricted group",
            schedule_values=("custom", "0,1,2,3,4", "08:00", "18:00"),
        )
        tv_id = self.store.add_tv("Lobby", "192.0.2.81", "generic_dlna")
        self.store.set_tv_group(tv_id, group_id)
        client, _ = self.as_user("tv-only", frozenset({"tv.view"}))

        tvs = client.get("/api/v1/tvs").json()["tvs"]
        status_tvs = client.get("/api/v1/status").json()["tvs"]

        self.assertNotIn("schedule_groups", next(tv for tv in tvs if tv["id"] == tv_id))
        self.assertNotIn("schedule_groups", next(tv for tv in status_tvs if tv["id"] == tv_id))


class MediaLifecycleGateTests(AuthzTestCase):
    """Publishing and destroying are gated on their own permissions.

    The object-level checks would refuse these callers too, which is the point
    of having both -- so each test also reads the audit line, because only the
    route gate names the permission the caller was missing. Remove the
    `require_permission("media.approve")` on the publish route and the audit
    assertion is what fails.
    """

    def add_clip(self, title: str = "Clip", state: str = "draft") -> int:
        source = Path(self.tmp.name) / f"{title}.mp4"
        source.write_bytes(b"video")
        media_id = self.store.add_media(title, source, f"{title}.mp4", 5, title, 10)
        self.store.set_media_lifecycle(media_id, state)
        return media_id

    def denial_details(self) -> str:
        return " ".join(str(event["details"] or "") for event in self.store.list_events(None, "security_denied", 10))

    def test_publishing_needs_media_approve(self):
        media_id = self.add_clip()
        client, csrf = self.as_user("editor", frozenset({"media.view", "media.manage"}))

        response = self.post(f"/api/v1/media/{media_id}/publish", {}, client, csrf)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.get_media(media_id)["lifecycle"], "draft")
        self.assertIn("missing media.approve", self.denial_details())

    def test_media_approve_publishes(self):
        media_id = self.add_clip()
        client, csrf = self.as_user("approver", frozenset({"media.view", "media.approve"}))

        response = self.post(f"/api/v1/media/{media_id}/publish", {}, client, csrf)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store.get_media(media_id)["lifecycle"], "published")

    def test_destroying_needs_media_purge(self):
        media_id = self.add_clip("Old", "archived")
        client, csrf = self.as_user("remover", frozenset({"media.view", "media.delete"}))

        response = self.post(f"/api/v1/media/{media_id}/purge", {}, client, csrf)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNotNone(self.store.get_media(media_id))
        self.assertIn("missing media.purge", self.denial_details())

    def test_deleting_only_archives(self):
        media_id = self.add_clip("Live", "published")
        client, csrf = self.as_user("archivist", frozenset({"media.view", "media.delete"}))

        response = self.delete(f"/api/v1/media/{media_id}", client, csrf)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store.get_media(media_id)["lifecycle"], "archived")


class BuiltinRoleParityTests(AuthzTestCase):
    """The three shipped roles must behave exactly as their old level did."""

    CASES = [
        ("viewer", "get", "/api/v1/tvs", 200),
        ("viewer", "get", "/api/v1/media", 200),
        ("viewer", "get", "/api/v1/playlists", 200),
        ("viewer", "get", "/api/v1/status", 200),
        ("viewer", "get", "/api/v1/events", 200),
        ("viewer", "get", "/api/v1/schedule", 200),
        ("viewer", "get", "/api/v1/groups", 200),
        ("viewer", "get", "/api/v1/nodes", 403),
        ("viewer", "get", "/api/v1/users", 403),
        ("viewer", "get", "/api/v1/profiles", 403),
        ("viewer", "get", "/api/v1/diagnostics", 403),
        ("viewer", "get", "/api/v1/tvs/scan", 403),
        ("operator", "get", "/api/v1/tvs", 200),
        ("operator", "get", "/api/v1/events", 200),
        ("operator", "get", "/api/v1/nodes", 403),
        ("operator", "get", "/api/v1/users", 403),
        ("operator", "get", "/api/v1/diagnostics", 403),
        ("admin", "get", "/api/v1/nodes", 200),
        ("admin", "get", "/api/v1/users", 200),
        ("admin", "get", "/api/v1/diagnostics", 200),
        ("admin", "get", "/api/v1/profiles", 200),
        ("admin", "get", "/api/v1/roles", 200),
    ]

    def test_reads_answer_as_they_did_before(self):
        clients = {}
        for role in ("viewer", "operator", "admin"):
            self.store.create_user(f"r-{role}", TEST_ADMIN_PASSWORD, role)
            client = TestClient(self.web.app)
            self.login(client, f"r-{role}", TEST_ADMIN_PASSWORD)
            clients[role] = client

        for role, method, url, expected in self.CASES:
            with self.subTest(role=role, url=url):
                response = getattr(clients[role], method)(url)
                self.assertEqual(response.status_code, expected, f"{role} {method} {url}: {response.text}")

    def test_writes_answer_as_they_did_before(self):
        cases = [
            ("viewer", "/api/v1/playlists", 403),
            ("operator", "/api/v1/playlists", 200),
            ("admin", "/api/v1/playlists", 200),
        ]
        for index, (role, url, expected) in enumerate(cases):
            with self.subTest(role=role):
                self.store.create_user(f"w-{role}", TEST_ADMIN_PASSWORD, role)
                client = TestClient(self.web.app)
                csrf = self.login(client, f"w-{role}", TEST_ADMIN_PASSWORD)
                response = self.post(url, {"name": f"list-{index}"}, client, csrf)
                self.assertEqual(response.status_code, expected, response.text)


class PrivilegeEscalationTests(AuthzTestCase):
    """You may not acquire authority you were not given."""

    def test_role_manager_cannot_mint_a_role_stronger_than_itself(self):
        client, csrf = self.as_user("minter", frozenset({"role.manage"}))

        response = self.post(
            "/api/v1/roles",
            {"name": "Superuser", "permissions": ["role.manage", "user.manage", "tv.manage"]},
            client,
            csrf,
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("user.manage", response.text)
        self.assertIsNone(self.store.get_role_by_name("Superuser"))

    def test_role_manager_can_mint_a_role_within_its_own_authority(self):
        client, csrf = self.as_user("fair", frozenset({"role.manage", "tv.view"}))

        response = self.post("/api/v1/roles", {"name": "Watcher", "permissions": ["tv.view"]}, client, csrf)

        self.assertEqual(response.status_code, 200, response.text)

    def test_role_manager_cannot_widen_an_existing_role(self):
        role_id = self.store.create_role("Narrow", "", frozenset({"tv.view"}))
        client, csrf = self.as_user("widener", frozenset({"role.manage", "tv.view"}))

        response = self.patch(
            f"/api/v1/roles/{role_id}",
            {"name": "Narrow", "permissions": ["tv.view", "user.manage"]},
            client,
            csrf,
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.role_permissions(role_id), frozenset({"tv.view"}))

    def test_role_manager_cannot_assign_a_role_beyond_its_authority(self):
        strong = self.store.create_role("Strong", "", frozenset({"user.manage"}))
        target = self.store.create_user("target", TEST_ADMIN_PASSWORD, "viewer")
        client, csrf = self.as_user("assigner", frozenset({"role.manage"}))

        response = self.put(f"/api/v1/users/{target}/roles", {"assignments": [{"role_id": strong, "scope_type": "global"}]}, client, csrf)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertNotIn("user.manage", self.store.user_permissions(target))

    def test_user_manager_cannot_create_an_admin(self):
        """The obvious escalation: make an admin, then log in as them."""
        client, csrf = self.as_user("maker", frozenset({"user.manage"}))

        response = self.post(
            "/api/v1/users",
            {"username": "backdoor", "password": TEST_ADMIN_PASSWORD, "role": "admin"},
            client,
            csrf,
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNone(self.store.get_user_by_username("backdoor"))

    def test_user_manager_cannot_promote_anybody_to_admin(self):
        target = self.store.create_user("pawn", TEST_ADMIN_PASSWORD, "viewer")
        client, csrf = self.as_user("promoter", frozenset({"user.manage"}))

        response = self.patch(f"/api/v1/users/{target}", {"role": "admin", "disabled": False}, client, csrf)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.get_user(target)["role"], "viewer")
        self.assertNotIn("role.manage", self.store.user_permissions(target))

    def test_user_manager_may_still_create_a_role_it_covers(self):
        client, csrf = self.as_user("hr", permissions.BUILTIN_ROLES["viewer"] | {"user.manage"})

        response = self.post(
            "/api/v1/users",
            {"username": "newbie", "password": TEST_ADMIN_PASSWORD, "role": "viewer"},
            client,
            csrf,
        )

        self.assertEqual(response.status_code, 200, response.text)

    def test_builtin_roles_cannot_be_edited(self):
        admin_role = self.store.get_role_by_name("admin")

        response = self.patch(f"/api/v1/roles/{admin_role['id']}", {"name": "admin", "permissions": ["tv.view"]})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.store.role_permissions(int(admin_role["id"])), permissions.KEYS)

    def test_builtin_roles_cannot_be_deleted(self):
        admin_role = self.store.get_role_by_name("admin")

        response = self.delete(f"/api/v1/roles/{admin_role['id']}")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIsNotNone(self.store.get_role_by_name("admin"))

    def test_a_custom_role_cannot_squat_a_builtin_name(self):
        response = self.post("/api/v1/roles", {"name": "admin", "permissions": []})
        self.assertEqual(response.status_code, 400, response.text)

    def test_duplicate_role_names_are_refused(self):
        self.post("/api/v1/roles", {"name": "Signage", "permissions": []})
        again = self.post("/api/v1/roles", {"name": "Signage", "permissions": []})
        self.assertEqual(again.status_code, 409, again.text)

    def test_unknown_permissions_are_refused(self):
        response = self.post("/api/v1/roles", {"name": "Bogus", "permissions": ["tv.view", "root.everything"]})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("root.everything", response.text)


class LockoutTests(AuthzTestCase):
    """The installation must never end up with nobody able to administer it."""

    def sole_administrator(self) -> tuple[int, TestClient, str]:
        """A custom role that is the only remaining source of authority.

        The built-in admin is demoted afterwards, so the person making the
        request holds their authority through the very role under test -- which
        is the only way the last-source case can actually be reached.
        """
        role_id = self.store.create_role("Deputy", "", frozenset({"role.manage", "user.manage"}))
        only = self.store.create_user("only", TEST_ADMIN_PASSWORD, "viewer")
        self.store.set_user_roles(only, [{"role_id": role_id, "scope_type": "global", "scope_id": None}])
        self.store.update_user(1, "viewer", False)
        client = TestClient(self.web.app)
        return role_id, client, self.login(client, "only", TEST_ADMIN_PASSWORD)

    def test_the_last_source_of_role_management_cannot_be_stripped(self):
        role_id, client, csrf = self.sole_administrator()

        response = self.patch(
            f"/api/v1/roles/{role_id}",
            {"name": "Deputy", "permissions": ["user.manage"]},
            client,
            csrf,
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("role.manage", response.text)
        self.assertIn("role.manage", self.store.role_permissions(role_id))

    def test_the_last_source_of_role_management_cannot_be_deleted(self):
        role_id, client, csrf = self.sole_administrator()

        response = self.delete(f"/api/v1/roles/{role_id}", client, csrf)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIsNotNone(self.store.get_role(role_id))

    def test_the_last_administrator_cannot_have_their_roles_cleared(self):
        response = self.put("/api/v1/users/1/roles", {"assignments": []})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn(1, self.store.users_with_permission("role.manage"))

    def test_clearing_roles_is_fine_while_somebody_else_still_administers(self):
        spare = self.store.create_user("spare", TEST_ADMIN_PASSWORD, "admin")
        target = self.store.create_user("target", TEST_ADMIN_PASSWORD, "admin")

        response = self.put(f"/api/v1/users/{target}/roles", {"assignments": []})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store.user_permissions(target), frozenset())
        self.assertIn(spare, self.store.users_with_permission("role.manage"))

    def test_a_role_can_still_be_deleted_when_it_carries_no_authority(self):
        role_id = self.store.create_role("Signage", "", frozenset({"tv.view"}))

        response = self.delete(f"/api/v1/roles/{role_id}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(self.store.get_role(role_id))


class CsrfTests(AuthzTestCase):
    def test_role_writes_still_require_csrf(self):
        for method, url in [
            ("post", "/api/v1/roles"),
            ("patch", "/api/v1/roles/1"),
            ("delete", "/api/v1/roles/1"),
            ("put", "/api/v1/users/1/roles"),
        ]:
            with self.subTest(url=url):
                response = self.client.request(method.upper(), url, json={"name": "x", "permissions": []})
                self.assertEqual(response.status_code, 403, response.text)

    def test_role_endpoints_reject_anonymous_callers(self):
        anonymous = TestClient(self.web.app)
        for url in ["/api/v1/roles", "/api/v1/permissions"]:
            with self.subTest(url=url):
                self.assertEqual(anonymous.get(url).status_code, 401)


if __name__ == "__main__":
    unittest.main()
