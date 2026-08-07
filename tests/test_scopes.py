"""Scoped grants: a branch operator sees and commands only their branch.

Until now a permission applied everywhere, so `/api/v1/status` handed every
screen in the company to anybody who could log in. These tests are mostly about
what a caller *cannot* see -- filtering, not gates, is where the disclosure
was.
"""

import importlib
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from screenloop import permissions

TEST_PASSWORD = "test-admin-password"
TEST_SECRET_KEY = "test-secret-key-that-is-long-enough-0123456789"


class ScopeTestCase(unittest.TestCase):
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
                "SCREENLOOP_BOOTSTRAP_PASSWORD": TEST_PASSWORD,
                "SCREENLOOP_SECRET_KEY": TEST_SECRET_KEY,
                "SCREENLOOP_ALLOWED_TV_CIDRS": "192.0.2.0/24",
            }
        )
        for name in list(sys.modules):
            if name == "screenloop" or name.startswith("screenloop."):
                sys.modules.pop(name, None)
        self.web = importlib.import_module("screenloop.web")
        self.web.config.ensure_dirs()
        self.web.store.ensure_bootstrap_admin("admin", TEST_PASSWORD)
        self.store = self.web.store
        self.client = TestClient(self.web.app)
        self.csrf = self.login(self.client, "admin")

        # Two branches, one screen each, plus an ungrouped screen.
        self.north = self.store.create_group("Север", None)
        self.north_floor = self.store.create_group("1-й этаж", self.north)
        self.south = self.store.create_group("Юг", None)
        self.node_id, _ = self.store.create_node("Выносная нода")

        self.tv_north = self.make_tv("Север-холл", "192.0.2.11", group_id=self.north_floor)
        self.tv_south = self.make_tv("Юг-холл", "192.0.2.12", group_id=self.south)
        self.tv_loose = self.make_tv("Без группы", "192.0.2.13")
        self.tv_node = self.make_tv("На ноде", "192.0.2.14", node_id=self.node_id)

    def login(self, client: TestClient, username: str) -> str:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": TEST_PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["csrf_token"]

    def make_tv(self, name: str, ip: str, group_id=None, node_id=None) -> int:
        tv_id = self.store.add_tv(name, ip, "generic_dlna")
        if group_id is not None:
            self.store.execute("UPDATE tvs SET group_id = ? WHERE id = ?", (group_id, tv_id))
        if node_id is not None:
            self.store.set_tv_node(tv_id, node_id)
        return tv_id

    def as_scoped(self, username: str, granted: frozenset[str], scope_type: str, scope_id):
        """A user holding `granted` only within one scope."""
        user_id = self.store.create_user(username, TEST_PASSWORD, "viewer")
        role_id = self.store.create_role(f"role-{username}", "", granted)
        self.store.set_user_roles(user_id, [{"role_id": role_id, "scope_type": scope_type, "scope_id": scope_id}])
        client = TestClient(self.web.app)
        return client, self.login(client, username)

    def tv_names(self, client: TestClient) -> set[str]:
        return {tv["name"] for tv in client.get("/api/v1/status").json()["tvs"]}


class ResolverTests(ScopeTestCase):
    def test_a_grant_on_a_parent_covers_the_child(self):
        scopes = permissions.Scopes((("tv.view", "group", self.north),), self.store.group_parents())
        self.assertTrue(scopes.covers("tv.view", group_id=self.north_floor))

    def test_a_grant_on_a_child_does_not_cover_the_parent(self):
        scopes = permissions.Scopes((("tv.view", "group", self.north_floor),), self.store.group_parents())
        self.assertFalse(scopes.covers("tv.view", group_id=self.north))

    def test_branches_do_not_cover_each_other(self):
        scopes = permissions.Scopes((("tv.view", "group", self.north),), self.store.group_parents())
        self.assertFalse(scopes.covers("tv.view", group_id=self.south))

    def test_a_global_grant_covers_everything(self):
        scopes = permissions.Scopes((("tv.view", "global", None),), self.store.group_parents())
        self.assertTrue(scopes.covers("tv.view", group_id=self.south))
        self.assertTrue(scopes.covers("tv.view", node_id=self.node_id))
        self.assertTrue(scopes.covers("tv.view"))

    def test_a_group_grant_does_not_cover_an_ungrouped_object(self):
        scopes = permissions.Scopes((("tv.view", "group", self.north),), self.store.group_parents())
        self.assertFalse(scopes.covers("tv.view", group_id=None))

    def test_a_node_grant_covers_only_that_node(self):
        scopes = permissions.Scopes((("tv.view", "node", self.node_id),), self.store.group_parents())
        self.assertTrue(scopes.covers("tv.view", node_id=self.node_id))
        self.assertFalse(scopes.covers("tv.view", node_id=self.node_id + 1))

    def test_a_cycle_in_the_tree_does_not_hang_the_resolver(self):
        """Corrupt parent pointers must fail closed, not spin."""
        scopes = permissions.Scopes((("tv.view", "group", 99),), {1: 2, 2: 1})
        self.assertEqual(scopes.ancestors(1), frozenset({1, 2}))


class DashboardFilteringTests(ScopeTestCase):
    def test_a_branch_operator_sees_only_their_branch(self):
        client, _ = self.as_scoped("north", frozenset({"tv.view"}), "group", self.north)

        self.assertEqual(self.tv_names(client), {"Север-холл"})

    def test_the_grant_reaches_down_the_subtree(self):
        """The screen is on the floor below the granted group."""
        client, _ = self.as_scoped("north", frozenset({"tv.view"}), "group", self.north)
        self.assertIn("Север-холл", self.tv_names(client))

    def test_a_node_grant_shows_that_node_s_screens(self):
        client, _ = self.as_scoped("nodeop", frozenset({"tv.view"}), "node", self.node_id)

        self.assertEqual(self.tv_names(client), {"На ноде"})

    def test_a_global_grant_still_sees_everything(self):
        client, _ = self.as_scoped("everywhere", frozenset({"tv.view"}), "global", None)

        self.assertEqual(len(self.tv_names(client)), 4)

    def test_the_tv_list_endpoint_filters_too(self):
        client, _ = self.as_scoped("north", frozenset({"tv.view"}), "group", self.north)

        names = {tv["name"] for tv in client.get("/api/v1/tvs").json()["tvs"]}

        self.assertEqual(names, {"Север-холл"})

    def test_the_sse_snapshot_filters_too(self):
        """The live stream is a second door to the same data."""
        user = self.store.get_user_by_username("admin")
        client, _ = self.as_scoped("north", frozenset({"tv.view", "event.view"}), "group", self.north)
        scoped = self.store.get_user_by_username("north")
        scoped["permissions"] = self.store.user_permissions(int(scoped["id"]))

        snapshot = self.web.live_snapshot(scoped)

        self.assertEqual({tv["name"] for tv in snapshot["status"]["tvs"]}, {"Север-холл"})
        self.assertIsNotNone(user)

    def test_events_about_invisible_screens_are_hidden(self):
        self.store.add_event(self.tv_south, "push_media", "Pushed to the south")
        self.store.add_event(self.tv_north, "push_media", "Pushed to the north")
        client, _ = self.as_scoped("north", frozenset({"tv.view", "event.view"}), "group", self.north)

        messages = {e["message"] for e in client.get("/api/v1/events").json()["events"]}

        self.assertIn("Pushed to the north", messages)
        self.assertNotIn("Pushed to the south", messages)

    def test_groups_outside_the_grant_are_hidden_but_ancestors_remain(self):
        """Hiding the parent too would leave the branch floating at the root."""
        client, _ = self.as_scoped("north", frozenset({"group.view"}), "group", self.north_floor)

        names = {g["name"] for g in client.get("/api/v1/groups").json()["groups"]}

        self.assertEqual(names, {"Север", "1-й этаж"})

    def test_nodes_outside_the_grant_are_hidden(self):
        other, _ = self.store.create_node("Чужая нода")
        client, _ = self.as_scoped("nodeop", frozenset({"node.view"}), "node", self.node_id)

        names = {n["name"] for n in client.get("/api/v1/nodes").json()["nodes"]}

        self.assertEqual(names, {"Выносная нода"})
        self.assertTrue(other)


class ObjectGateTests(ScopeTestCase):
    def command(self, client, csrf, tv_id, command="stop"):
        return client.post(f"/api/v1/tvs/{tv_id}/commands", json={"command": command}, headers={"X-CSRF-Token": csrf})

    def test_commanding_your_own_branch_is_allowed(self):
        client, csrf = self.as_scoped("north", frozenset({"tv.view", "tv.command"}), "group", self.north)

        self.assertEqual(self.command(client, csrf, self.tv_north).status_code, 200)

    def test_commanding_another_branch_is_refused(self):
        client, csrf = self.as_scoped("north", frozenset({"tv.view", "tv.command"}), "group", self.north)

        response = self.command(client, csrf, self.tv_south)

        self.assertEqual(response.status_code, 403, response.text)

    def test_the_refusal_is_written_to_the_audit_log(self):
        client, csrf = self.as_scoped("north", frozenset({"tv.view", "tv.command"}), "group", self.north)
        self.command(client, csrf, self.tv_south)

        denials = self.store.list_events(None, "security_denied", 5)

        self.assertTrue(denials)
        self.assertIn("tv.command", denials[0]["message"])

    def test_deleting_a_screen_in_another_branch_is_refused(self):
        client, csrf = self.as_scoped("north", frozenset({"tv.view", "tv.manage"}), "group", self.north)

        response = client.delete(f"/api/v1/tvs/{self.tv_south}", headers={"X-CSRF-Token": csrf})

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNotNone(self.store.get_tv(self.tv_south))

    def test_a_screen_cannot_be_moved_into_a_branch_you_do_not_hold(self):
        """Otherwise a branch admin could push their screens into somebody else's tree."""
        client, csrf = self.as_scoped("north", frozenset({"tv.view", "tv.manage"}), "group", self.north)

        response = client.patch(
            f"/api/v1/tvs/{self.tv_north}",
            json={"name": "Север-холл", "ip": "192.0.2.11", "profile": "generic_dlna", "group_id": self.south},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.get_tv(self.tv_north)["group_id"], self.north_floor)

    def test_renaming_a_group_in_another_branch_is_refused(self):
        client, csrf = self.as_scoped("north", frozenset({"group.view", "group.manage"}), "group", self.north)

        response = client.patch(
            f"/api/v1/groups/{self.south}",
            json={"name": "Захвачено"},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.get_group(self.south)["name"], "Юг")

    def test_managing_another_node_is_refused(self):
        other_id, _ = self.store.create_node("Чужая нода")
        client, csrf = self.as_scoped("nodeop", frozenset({"node.view", "node.manage"}), "node", self.node_id)

        response = client.delete(f"/api/v1/nodes/{other_id}", headers={"X-CSRF-Token": csrf})

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNotNone(self.store.get_node(other_id))


class ScopedEscalationTests(ScopeTestCase):
    def put_roles(self, client, csrf, user_id, assignments):
        return client.put(
            f"/api/v1/users/{user_id}/roles",
            json={"assignments": assignments},
            headers={"X-CSRF-Token": csrf},
        )

    def test_you_cannot_grant_beyond_your_own_scope(self):
        """A branch role manager must not hand out authority over other branches."""
        role_id = self.store.create_role("Команда", "", frozenset({"tv.command"}))
        target = self.store.create_user("target", TEST_PASSWORD, "viewer")
        client, csrf = self.as_scoped("branchadmin", frozenset({"role.manage", "tv.command"}), "group", self.north)

        response = self.put_roles(client, csrf, target, [{"role_id": role_id, "scope_type": "group", "scope_id": self.south}])

        self.assertEqual(response.status_code, 403, response.text)
        # The target keeps the viewer role it was created with; what must not
        # exist is any grant over the other branch.
        self.assertNotIn(("tv.command", "group", self.south), self.store.user_grants(target))

    def test_you_can_grant_within_your_own_scope(self):
        role_id = self.store.create_role("Команда", "", frozenset({"tv.command"}))
        target = self.store.create_user("target", TEST_PASSWORD, "viewer")
        client, csrf = self.as_scoped("branchadmin", frozenset({"role.manage", "tv.command"}), "group", self.north)

        response = self.put_roles(
            client, csrf, target, [{"role_id": role_id, "scope_type": "group", "scope_id": self.north_floor}]
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(("tv.command", "group", self.north_floor), self.store.user_grants(target))

    def test_a_scoped_grant_cannot_be_widened_to_global(self):
        role_id = self.store.create_role("Команда", "", frozenset({"tv.command"}))
        target = self.store.create_user("target", TEST_PASSWORD, "viewer")
        client, csrf = self.as_scoped("branchadmin", frozenset({"role.manage", "tv.command"}), "group", self.north)

        response = self.put_roles(client, csrf, target, [{"role_id": role_id, "scope_type": "global"}])

        self.assertEqual(response.status_code, 403, response.text)

    def test_a_branch_administrator_does_not_count_as_the_last_administrator(self):
        """Somebody confined to one branch cannot administer the installation."""
        role_id = self.store.create_role("Филиальный админ", "", permissions.KEYS)
        branch_admin = self.store.create_user("branchadmin", TEST_PASSWORD, "viewer")
        self.store.set_user_roles(
            branch_admin, [{"role_id": role_id, "scope_type": "group", "scope_id": self.north}]
        )

        self.assertNotIn(branch_admin, self.store.users_with_global_permission("role.manage"))

        response = self.put_roles(self.client, self.csrf, 1, [])

        self.assertEqual(response.status_code, 400, response.text)

    def test_an_unknown_scope_type_is_refused(self):
        role_id = self.store.create_role("Команда", "", frozenset({"tv.command"}))
        target = self.store.create_user("target", TEST_PASSWORD, "viewer")

        response = self.put_roles(self.client, self.csrf, target, [{"role_id": role_id, "scope_type": "planet"}])

        self.assertEqual(response.status_code, 400, response.text)

    def test_a_scope_needs_an_id(self):
        role_id = self.store.create_role("Команда", "", frozenset({"tv.command"}))
        target = self.store.create_user("target", TEST_PASSWORD, "viewer")

        response = self.put_roles(self.client, self.csrf, target, [{"role_id": role_id, "scope_type": "group"}])

        self.assertEqual(response.status_code, 400, response.text)


class MigrationTests(ScopeTestCase):
    def test_existing_grants_became_global(self):
        """Nobody's access may change on upgrade."""
        for permission, scope_type, scope_id in self.store.user_grants(1):
            self.assertEqual(scope_type, "global", permission)
            self.assertIsNone(scope_id)

    def test_the_bootstrap_admin_still_sees_every_screen(self):
        self.assertEqual(len(self.tv_names(self.client)), 4)


if __name__ == "__main__":
    unittest.main()
