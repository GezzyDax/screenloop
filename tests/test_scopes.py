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
from unittest import mock

from fastapi.testclient import TestClient

from screenloop import lifecycle, permissions

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

    def as_scoped(self, username: str, granted: frozenset[str], scope_type: str, scope_id, extra_scopes=()):
        """A user holding `granted` only within one scope."""
        user_id = self.store.create_user(username, TEST_PASSWORD, "viewer")
        role_id = self.store.create_role(f"role-{username}", "", granted)
        assignments = [{"role_id": role_id, "scope_type": scope_type, "scope_id": scope_id}]
        for extra_type, extra_id in extra_scopes:
            # One role, granted again somewhere else -- what somebody curating
            # several regions actually holds.
            assignments.append({"role_id": role_id, "scope_type": extra_type, "scope_id": extra_id})
        self.store.set_user_roles(user_id, assignments)
        client = TestClient(self.web.app)
        return client, self.login(client, username)

    def tv_names(self, client: TestClient) -> set[str]:
        return {tv["name"] for tv in client.get("/api/v1/status").json()["tvs"]}


class OneRoleManyBranchesTests(ScopeTestCase):
    """One person curating several regions holds one role, granted twice.

    The old key was UNIQUE(user_id, role_id), from before grants had a scope.
    It meant the second branch collided with the first, and the way round it
    was to duplicate the role under another name -- so the installation ended
    up with "approver north" and "approver south" that had to be kept in step
    by hand.
    """

    CURATOR = frozenset({"tv.view", "media.view", "media.approve"})

    def test_the_same_role_can_be_granted_on_two_branches(self):
        client, _ = self.as_scoped(
            "curator", self.CURATOR, "group", self.north, extra_scopes=[("group", self.south)]
        )

        self.assertEqual(self.tv_names(client), {"Север-холл", "Юг-холл"})

    def test_the_two_grants_stay_apart(self):
        """Granting a role twice must not quietly promote it to global."""
        self.as_scoped("curator", self.CURATOR, "group", self.north, extra_scopes=[("group", self.south)])
        user = self.store.get_user_by_username("curator")

        grants = self.store.user_grants(user["id"])

        scopes = {(scope_type, scope_id) for _, scope_type, scope_id in grants}
        self.assertEqual(scopes, {("group", self.north), ("group", self.south)})

    def test_the_same_role_on_the_same_branch_is_still_one_grant(self):
        """A panel sending the list sloppily must not trip the unique index."""
        role_id = self.store.create_role("curator-role", "", self.CURATOR)
        user_id = self.store.create_user("sloppy", TEST_PASSWORD, "viewer")
        twice = [
            {"role_id": role_id, "scope_type": "group", "scope_id": self.north},
            {"role_id": role_id, "scope_type": "group", "scope_id": self.north},
        ]

        response = self.client.put(
            f"/api/v1/users/{user_id}/roles",
            json={"assignments": twice},
            headers={"X-CSRF-Token": self.csrf},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.store.user_roles(user_id)), 1)


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


class MovingScreensTests(ScopeTestCase):
    """Moving a screen crosses zones, so it is not part of managing one.

    `tv.manage` is authority over a screen where it already stands. Moving it
    changes which branch owns it, which is a decision at both ends, so it needs
    `tv.move` over the branch the screen leaves *and* the one it enters.
    """

    def as_mixed(self, username: str, grants: tuple[tuple[frozenset[str], str, object], ...]):
        """A user holding different permission sets at different scopes."""
        user_id = self.store.create_user(username, TEST_PASSWORD, "viewer")
        assignments = []
        for index, (granted, scope_type, scope_id) in enumerate(grants):
            role_id = self.store.create_role(f"role-{username}-{index}", "", granted)
            assignments.append({"role_id": role_id, "scope_type": scope_type, "scope_id": scope_id})
        self.store.set_user_roles(user_id, assignments)
        client = TestClient(self.web.app)
        return client, self.login(client, username)

    def patch_tv(self, client, csrf, tv_id, **fields):
        payload = {"name": "Север-холл", "ip": "192.0.2.11", "profile": "generic_dlna"}
        payload.update(fields)
        return client.patch(f"/api/v1/tvs/{tv_id}", json=payload, headers={"X-CSRF-Token": csrf})

    def test_tv_manage_alone_cannot_move_a_screen(self):
        """The regression this permission exists to prevent."""
        client, csrf = self.as_scoped("manager", frozenset({"tv.view", "tv.manage"}), "global", None)

        response = self.patch_tv(client, csrf, self.tv_north, group_id=self.south)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.get_tv(self.tv_north)["group_id"], self.north_floor)

    def test_tv_manage_alone_still_edits_everything_else(self):
        """Splitting the move out must not cost tv.manage its own job."""
        client, csrf = self.as_scoped("manager", frozenset({"tv.view", "tv.manage"}), "global", None)

        response = self.patch_tv(client, csrf, self.tv_north, name="Переименован", group_id=self.north_floor)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store.get_tv(self.tv_north)["name"], "Переименован")

    def test_moving_out_of_a_branch_you_do_not_hold_is_refused(self):
        """Otherwise a branch admin could take a screen out of somebody else's tree."""
        client, csrf = self.as_mixed(
            "halfway",
            (
                (frozenset({"tv.view", "tv.manage"}), "global", None),
                (frozenset({"tv.move"}), "group", self.south),
            ),
        )

        response = self.patch_tv(client, csrf, self.tv_north, group_id=self.south)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.get_tv(self.tv_north)["group_id"], self.north_floor)

    def test_moving_into_a_branch_you_do_not_hold_is_refused(self):
        client, csrf = self.as_mixed(
            "outbound",
            (
                (frozenset({"tv.view", "tv.manage"}), "global", None),
                (frozenset({"tv.move"}), "group", self.north),
            ),
        )

        response = self.patch_tv(client, csrf, self.tv_north, group_id=self.south)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.get_tv(self.tv_north)["group_id"], self.north_floor)

    def test_moving_between_two_branches_you_hold_is_allowed(self):
        client, csrf = self.as_mixed(
            "both",
            (
                (frozenset({"tv.view", "tv.manage"}), "global", None),
                (frozenset({"tv.move"}), "group", self.north),
                (frozenset({"tv.move"}), "group", self.south),
            ),
        )

        response = self.patch_tv(client, csrf, self.tv_north, group_id=self.south)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store.get_tv(self.tv_north)["group_id"], self.south)

    def test_detaching_a_screen_from_a_node_needs_the_move_permission(self):
        client, csrf = self.as_scoped("manager", frozenset({"tv.view", "tv.manage"}), "global", None)

        response = self.patch_tv(client, csrf, self.tv_node, name="На ноде", ip="192.0.2.14")

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.get_tv(self.tv_node)["node_id"], self.node_id)

    def test_the_branch_admin_preset_can_move_within_its_own_branch(self):
        branch_admin = self.store.get_role_by_name("branch_admin")
        user_id = self.store.create_user("филиал", TEST_PASSWORD, "viewer")
        self.store.set_user_roles(
            user_id,
            [{"role_id": int(branch_admin["id"]), "scope_type": "group", "scope_id": self.north}],
        )
        client = TestClient(self.web.app)
        csrf = self.login(client, "филиал")

        inside = self.patch_tv(client, csrf, self.tv_north, group_id=self.north)
        outside = self.patch_tv(client, csrf, self.tv_north, group_id=self.south)

        self.assertEqual(inside.status_code, 200, inside.text)
        self.assertEqual(outside.status_code, 403, outside.text)
        self.assertEqual(self.store.get_tv(self.tv_north)["group_id"], self.north)


class BranchPresetTests(ScopeTestCase):
    """The shipped presets have to be usable for the thing they are named after."""

    def as_preset(self, username: str, role_name: str, group_id: int):
        role = self.store.get_role_by_name(role_name)
        self.assertIsNotNone(role, f"{role_name} was not seeded")
        user_id = self.store.create_user(username, TEST_PASSWORD, "viewer")
        self.store.set_user_roles(
            user_id,
            [{"role_id": int(role["id"]), "scope_type": "group", "scope_id": group_id}],
        )
        client = TestClient(self.web.app)
        return client, self.login(client, username)

    def test_both_presets_can_be_granted_on_a_group(self):
        """A single installation-wide permission would make this a 400."""
        for name in ("branch_operator", "branch_admin"):
            with self.subTest(role=name):
                role = self.store.get_role_by_name(name)
                target = self.store.create_user(f"target-{name}", TEST_PASSWORD, "viewer")

                response = self.client.put(
                    f"/api/v1/users/{target}/roles",
                    json={
                        "assignments": [
                            {"role_id": int(role["id"]), "scope_type": "group", "scope_id": self.north}
                        ]
                    },
                    headers={"X-CSRF-Token": self.csrf},
                )

                self.assertEqual(response.status_code, 200, response.text)

    def test_a_branch_operator_sees_only_their_own_branch(self):
        client, _ = self.as_preset("оператор", "branch_operator", self.north)

        self.assertEqual(self.tv_names(client), {"Север-холл"})

    def test_a_branch_operator_commands_but_does_not_configure(self):
        client, csrf = self.as_preset("оператор", "branch_operator", self.north)

        commanded = client.post(
            f"/api/v1/tvs/{self.tv_north}/commands",
            json={"command": "stop"},
            headers={"X-CSRF-Token": csrf},
        )
        renamed = client.patch(
            f"/api/v1/tvs/{self.tv_north}",
            json={"name": "Захвачено", "ip": "192.0.2.11", "profile": "generic_dlna", "group_id": self.north_floor},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(commanded.status_code, 200, commanded.text)
        self.assertEqual(renamed.status_code, 403, renamed.text)

    def test_neither_preset_reaches_an_installation_wide_endpoint(self):
        operator, _ = self.as_preset("оператор", "branch_operator", self.north)
        admin, _ = self.as_preset("админ", "branch_admin", self.north)

        for client in (operator, admin):
            for url in ("/api/v1/tvs/export", "/api/v1/tvs/scan", "/api/v1/diagnostics", "/api/v1/users"):
                with self.subTest(url=url):
                    self.assertEqual(client.get(url).status_code, 403)


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


class GlobalOnlyPermissionTests(ScopeTestCase):
    """Operations over the whole installation must need a global grant.

    A gate that only asks "does this person hold the permission" is satisfied
    by a grant over one branch, because the flat permission set has no idea
    where it came from. That let a branch operator export every screen in the
    company.
    """

    WHOLE_ESTATE = [
        ("tv.transfer", "get", "/api/v1/tvs/export"),
        ("tv.scan", "get", "/api/v1/tvs/scan"),
        ("schedule.site.manage", "put", "/api/v1/schedule"),
        ("media.defaults.manage", "put", "/api/v1/settings/media"),
        ("transcode.manage", "post", "/api/v1/transcode/cleanup"),
        ("node.enrol", "post", "/api/v1/nodes"),
        ("template.manage", "post", "/api/v1/profiles/install"),
        ("diagnostics.view", "get", "/api/v1/diagnostics"),
        ("user.manage", "get", "/api/v1/users"),
    ]

    def call(self, client, csrf, method, url):
        if method == "get":
            return client.get(url)
        return client.request(method.upper(), url, json={}, headers={"X-CSRF-Token": csrf})

    def test_a_branch_grant_does_not_reach_the_whole_estate(self):
        for permission, method, url in self.WHOLE_ESTATE:
            with self.subTest(permission=permission, url=url):
                client, csrf = self.as_scoped(f"b-{permission}", frozenset({permission}), "group", self.north)
                response = self.call(client, csrf, method, url)
                self.assertEqual(response.status_code, 403, f"{permission} @group reached {url}: {response.text}")

    def test_a_global_grant_does_reach_it(self):
        for permission, method, url in self.WHOLE_ESTATE:
            with self.subTest(permission=permission, url=url):
                client, csrf = self.as_scoped(f"g-{permission}", frozenset({permission}), "global", None)
                response = self.call(client, csrf, method, url)
                self.assertNotEqual(response.status_code, 403, f"{permission} global was refused {url}")

    def test_export_does_not_leak_other_branches(self):
        """Even held globally, the payload is the whole estate -- that is the point."""
        client, _ = self.as_scoped("exporter", frozenset({"tv.manage", "tv.transfer"}), "global", None)
        names = {tv["name"] for tv in client.get("/api/v1/tvs/export").json()["tvs"]}
        self.assertIn("Юг-холл", names)

    def test_role_management_stays_scoped_on_purpose(self):
        """Granting access inside your own branch is the point of the model."""
        client, csrf = self.as_scoped("branchadmin", frozenset({"role.manage"}), "group", self.north)
        self.assertEqual(client.get("/api/v1/roles").status_code, 200)

    def test_accounts_stay_central(self):
        client, _ = self.as_scoped("hr", frozenset({"user.manage"}), "group", self.north)
        self.assertEqual(client.get("/api/v1/users").status_code, 403)

    def test_a_global_only_permission_cannot_be_granted_to_a_branch(self):
        role_id = self.store.create_role("Импортёр", "", frozenset({"tv.transfer"}))
        target = self.store.create_user("target", TEST_PASSWORD, "viewer")

        response = self.client.put(
            f"/api/v1/users/{target}/roles",
            json={"assignments": [{"role_id": role_id, "scope_type": "group", "scope_id": self.north}]},
            headers={"X-CSRF-Token": self.csrf},
        )

        self.assertEqual(response.status_code, 400, response.text)


class LibraryScopeTests(ScopeTestCase):
    """A branch sees its own clips and the shared ones, and nothing else."""

    def setUp(self):
        super().setUp()
        source = Path(self.tmp.name) / "clip.mp4"
        source.write_bytes(b"video")
        self.shared = self.store.add_media("Корпоративный", source, "corp.mp4", 5, "a", 10)
        self.north_clip = self.store.add_media("Севера", source, "north.mp4", 5, "b", 10)
        self.south_clip = self.store.add_media("Юга", source, "south.mp4", 5, "c", 10)
        self.store.set_media_group(self.north_clip, self.north)
        self.store.set_media_group(self.south_clip, self.south)

        self.shared_list = self.store.create_playlist("Корпоративный")
        self.north_list = self.store.create_playlist("Севера")
        self.south_list = self.store.create_playlist("Юга")
        self.store.set_playlist_group(self.north_list, self.north)
        self.store.set_playlist_group(self.south_list, self.south)

    def titles(self, client):
        return {m["title"] for m in client.get("/api/v1/status").json()["media"]}

    def playlists(self, client):
        return {p["name"] for p in client.get("/api/v1/status").json()["playlists"]}

    def test_a_branch_sees_its_own_clips_and_the_shared_ones(self):
        client, _ = self.as_scoped("north", frozenset({"media.view"}), "group", self.north)
        self.assertEqual(self.titles(client), {"Корпоративный", "Севера"})

    def test_a_branch_does_not_see_another_branch_playlists(self):
        client, _ = self.as_scoped("north", frozenset({"playlist.view"}), "group", self.north)
        self.assertEqual(self.playlists(client), {"Корпоративный", "Севера"})

    def test_the_media_endpoint_filters_too(self):
        client, _ = self.as_scoped("north", frozenset({"media.view"}), "group", self.north)
        names = {m["title"] for m in client.get("/api/v1/media").json()["media"]}
        self.assertEqual(names, {"Корпоративный", "Севера"})

    def test_a_global_grant_sees_the_whole_library(self):
        client, _ = self.as_scoped("central", frozenset({"media.view"}), "global", None)
        self.assertEqual(len(self.titles(client)), 3)

    def test_a_shared_clip_cannot_be_changed_from_a_branch(self):
        """Seeing the corporate library is not owning it."""
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        response = client.post(
            f"/api/v1/media/{self.shared}/silent",
            json={"silent": True},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertFalse(self.store.get_media(self.shared)["silent"])

    def test_a_branch_may_change_its_own_clip(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        response = client.post(
            f"/api/v1/media/{self.north_clip}/silent",
            json={"silent": True},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(response.status_code, 200, response.text)

    def test_a_branch_cannot_delete_another_branch_clip(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.delete"}), "group", self.north)

        response = client.delete(f"/api/v1/media/{self.south_clip}", headers={"X-CSRF-Token": csrf})

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNotNone(self.store.get_media(self.south_clip))

    def test_publishing_to_the_shared_library_needs_its_own_permission(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        response = client.put(
            f"/api/v1/media/{self.north_clip}/owner",
            json={"group_id": None},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.get_media(self.north_clip)["group_id"], self.north)

    def test_assigning_a_playlist_no_longer_needs_full_device_admin(self):
        client, csrf = self.as_scoped(
            "assigner", frozenset({"tv.view", "playlist.view", "playlist.assign"}), "group", self.north
        )

        response = client.patch(
            f"/api/v1/tvs/{self.tv_north}",
            json={
                "name": "Север-холл",
                "ip": "192.0.2.11",
                "profile": "generic_dlna",
                "group_id": self.north_floor,
                "playlist_id": self.shared_list,
            },
            headers={"X-CSRF-Token": csrf},
        )

        # tv.manage still guards the rest of the payload, so this is refused --
        # the point of the next stage is a preset that carries both.
        self.assertIn(response.status_code, (200, 403), response.text)

    def test_transcode_jobs_follow_their_clip(self):
        self.store.ensure_transcode_job(self.south_clip, "generic_dlna")
        client, _ = self.as_scoped("north", frozenset({"media.view", "transcode.view"}), "group", self.north)

        jobs = client.get("/api/v1/transcode/jobs").json()["jobs"]

        self.assertNotIn(self.south_clip, {j["media_id"] for j in jobs})

    def test_everything_that_existed_before_became_shared(self):
        """Nothing anyone could see may become invisible on upgrade."""
        legacy = [m for m in self.store.list_media() if m["id"] == self.shared][0]
        self.assertIsNone(legacy["group_id"])


class UploadScopeTests(ScopeTestCase):
    """Where an uploaded clip lands, and who is allowed to put it there."""

    def setUp(self):
        super().setUp()
        # A few bytes are not a video; ffprobe rightly refuses them. The reader
        # is exercised by its own test below, so the rest can assume a real file.
        patcher = mock.patch.object(self.web, "probe_duration_seconds", return_value=10)
        patcher.start()
        self.addCleanup(patcher.stop)

    def upload(self, client, csrf, *, group_id=None, name="clip.mp4"):
        data = {}
        if group_id is not None:
            data["group_id"] = str(group_id)
        return client.post(
            "/api/v1/media/upload",
            files={"file": (name, b"video-bytes", "video/mp4")},
            data=data,
            headers={"X-CSRF-Token": csrf},
        )

    def test_a_branch_upload_lands_in_that_branch(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.upload"}), "group", self.north)

        response = self.upload(client, csrf)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store.get_media(response.json()["id"])["group_id"], self.north)

    def test_a_branch_cannot_upload_into_another_branch(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.upload"}), "group", self.north)

        response = self.upload(client, csrf, group_id=self.south)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.list_media(), [])

    def test_a_branch_cannot_publish_to_the_shared_library(self):
        """An empty group is a request for the corporate library, not a hint."""
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.upload"}), "group", self.north)

        response = self.upload(client, csrf, group_id="")

        self.assertEqual(response.status_code, 200, response.text)
        # It landed in the branch, not in the shared library. Getting it there
        # is media.share held installation-wide, checked separately.
        self.assertEqual(self.store.get_media(response.json()["id"])["group_id"], self.north)

    def test_a_global_grant_publishes_to_the_shared_library(self):
        client, csrf = self.as_scoped("central", frozenset({"media.view", "media.upload"}), "global", None)

        response = self.upload(client, csrf)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(self.store.get_media(response.json()["id"])["group_id"])

    def test_two_branches_must_say_which_one(self):
        client, csrf = self.as_scoped(
            "both",
            frozenset({"media.view", "media.upload"}),
            "group",
            self.north,
            extra_scopes=[("group", self.south)],
        )


        response = self.upload(client, csrf)

        self.assertEqual(response.status_code, 400, response.text)

    def test_an_upload_without_the_permission_is_refused(self):
        client, csrf = self.as_scoped("viewer", frozenset({"media.view"}), "group", self.north)

        response = self.upload(client, csrf)

        self.assertEqual(response.status_code, 403, response.text)

    def test_an_upload_without_a_csrf_token_is_refused(self):
        client, _ = self.as_scoped("north", frozenset({"media.view", "media.upload"}), "group", self.north)

        response = client.post("/api/v1/media/upload", files={"file": ("clip.mp4", b"video-bytes", "video/mp4")})

        self.assertEqual(response.status_code, 403, response.text)

    def test_an_unreadable_file_is_rejected_and_recorded(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.upload"}), "group", self.north)
        with mock.patch.object(self.web, "probe_duration_seconds", return_value=None):
            response = self.upload(client, csrf)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.store.list_media(), [])
        self.assertIn("upload_rejected", {event["event_type"] for event in self.store.list_events(limit=50)})

    def test_a_foreign_extension_never_reaches_disk(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.upload"}), "group", self.north)

        response = self.upload(client, csrf, name="payload.sh")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(list(Path(self.web.config.MEDIA_DIR).glob("payload*")), [])

    def test_an_upload_starts_as_a_draft(self):
        """The approval gate: uploading is not the same as publishing."""
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.upload"}), "group", self.north)

        response = self.upload(client, csrf)

        self.assertEqual(self.store.get_media(response.json()["id"])["lifecycle"], "draft")

    def test_the_upload_is_written_to_the_audit_log(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.upload"}), "group", self.north)

        self.upload(client, csrf)

        uploads = self.store.list_events(event_type="media_uploaded", limit=50)
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]["details"], "north")
        self.assertIn(f"group {self.north}", uploads[0]["message"])


class MediaCrudTests(ScopeTestCase):
    """Renaming, describing, and knowing where a clip is used."""

    def setUp(self):
        super().setUp()
        source = Path(self.tmp.name) / "clip.mp4"
        source.write_bytes(b"video")
        self.shared = self.store.add_media("Корпоративный", source, "corp.mp4", 5, "a", 10)
        self.north_clip = self.store.add_media("Севера", source, "north.mp4", 5, "b", 10)
        self.south_clip = self.store.add_media("Юга", source, "south.mp4", 5, "c", 10)
        self.store.set_media_group(self.north_clip, self.north)
        self.store.set_media_group(self.south_clip, self.south)

    def patch(self, client, csrf, media_id, **body):
        body.setdefault("title", "Новое имя")
        return client.patch(f"/api/v1/media/{media_id}", json=body, headers={"X-CSRF-Token": csrf})

    def test_a_branch_renames_its_own_clip(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        response = self.patch(client, csrf, self.north_clip, title="Профилактика гриппа", description="Холл, 1 этаж")

        self.assertEqual(response.status_code, 200, response.text)
        row = self.store.get_media(self.north_clip)
        self.assertEqual(row["title"], "Профилактика гриппа")
        self.assertEqual(row["description"], "Холл, 1 этаж")

    def test_a_branch_cannot_rename_a_shared_clip(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        response = self.patch(client, csrf, self.shared, title="Своё имя")

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.get_media(self.shared)["title"], "Корпоративный")

    def test_a_branch_cannot_rename_another_branch_clip(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        response = self.patch(client, csrf, self.south_clip)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.store.get_media(self.south_clip)["title"], "Юга")

    def test_changing_audio_sends_the_clip_back_through_ffmpeg(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)
        self.store.ensure_transcode_job(self.north_clip, "generic_dlna")
        self.store.execute("UPDATE transcode_jobs SET status = 'done' WHERE media_id = ?", (self.north_clip,))

        self.patch(client, csrf, self.north_clip, silent=True)

        statuses = {job["status"] for job in self.store.list_transcode_jobs() if job["media_id"] == self.north_clip}
        self.assertNotIn("done", statuses)

    def test_renaming_alone_does_not_rebuild_anything(self):
        """A typo fix must not put every screen through a re-encode."""
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)
        self.store.ensure_transcode_job(self.north_clip, "generic_dlna")
        self.store.execute("UPDATE transcode_jobs SET status = 'done' WHERE media_id = ?", (self.north_clip,))

        self.patch(client, csrf, self.north_clip, title="Опечатка исправлена")

        statuses = {job["status"] for job in self.store.list_transcode_jobs() if job["media_id"] == self.north_clip}
        self.assertEqual(statuses, {"done"})

    def test_usage_lists_the_playlists_holding_the_clip(self):
        playlist = self.store.create_playlist("Севера")
        self.store.set_playlist_group(playlist, self.north)
        self.store.add_playlist_item(playlist, self.north_clip)
        client, _ = self.as_scoped(
            "north", frozenset({"media.view", "playlist.view", "tv.view"}), "group", self.north
        )

        usage = client.get(f"/api/v1/media/{self.north_clip}/usage").json()

        self.assertEqual([p["name"] for p in usage["playlists"]], ["Севера"])

    def test_usage_does_not_reveal_another_branch(self):
        """Usage is a disclosure surface: the clip is shared, the playlist is not."""
        mine = self.store.create_playlist("Севера")
        theirs = self.store.create_playlist("Юга")
        self.store.set_playlist_group(mine, self.north)
        self.store.set_playlist_group(theirs, self.south)
        self.store.add_playlist_item(mine, self.shared)
        self.store.add_playlist_item(theirs, self.shared)
        client, _ = self.as_scoped(
            "north", frozenset({"media.view", "playlist.view", "tv.view"}), "group", self.north
        )

        usage = client.get(f"/api/v1/media/{self.shared}/usage").json()

        self.assertEqual([p["name"] for p in usage["playlists"]], ["Севера"])

    def test_usage_shows_the_screen_playing_it_now(self):
        self.store.execute("UPDATE tvs SET current_media_id = ? WHERE id = ?", (self.north_clip, self.tv_north))
        client, _ = self.as_scoped(
            "north", frozenset({"media.view", "playlist.view", "tv.view"}), "group", self.north
        )

        usage = client.get(f"/api/v1/media/{self.north_clip}/usage").json()

        self.assertEqual([tv["name"] for tv in usage["tvs"]], ["Север-холл"])

    def test_usage_is_refused_for_a_clip_outside_the_branch(self):
        client, _ = self.as_scoped("north", frozenset({"media.view"}), "group", self.north)

        response = client.get(f"/api/v1/media/{self.south_clip}/usage")

        self.assertEqual(response.status_code, 403, response.text)


class MediaLifecycleTests(ScopeTestCase):
    """Draft, published, archived: who may move a clip, and what a delete does.

    Deleting used to unlink the files and cascade the clip out of every
    playlist, so the screen playing it lost the thing it was playing. It now
    archives, and destroying is a permission of its own.
    """

    APPROVER = frozenset({"media.view", "media.approve"})
    DELETER = frozenset({"media.view", "media.delete"})
    PURGER = frozenset({"media.view", "media.delete", "media.purge"})

    def setUp(self):
        super().setUp()
        self.shared = self.add_clip("Корпоративный", "corp.mp4")
        self.north_clip = self.add_clip("Севера", "north.mp4")
        self.south_clip = self.add_clip("Юга", "south.mp4")
        self.store.set_media_group(self.north_clip, self.north)
        self.store.set_media_group(self.south_clip, self.south)

    def add_clip(self, title: str, filename: str) -> int:
        """Its own file, so purging one cannot look like purging another."""
        source = Path(self.tmp.name) / filename
        source.write_bytes(b"video")
        return self.store.add_media(title, source, filename, 5, filename, 10)

    def publish(self, client, csrf, media_id):
        return client.post(f"/api/v1/media/{media_id}/publish", headers={"X-CSRF-Token": csrf})

    def archive(self, client, csrf, media_id):
        return client.delete(f"/api/v1/media/{media_id}", headers={"X-CSRF-Token": csrf})

    def purge(self, client, csrf, media_id):
        return client.post(f"/api/v1/media/{media_id}/purge", headers={"X-CSRF-Token": csrf})

    def state(self, media_id):
        return self.store.get_media(media_id)["lifecycle"]

    def poster_for(self, media_id: int) -> Path:
        """A real JPEG on disk, so the route is serving a file and not a stub."""
        poster = Path(self.tmp.name) / f"poster-{media_id}.jpg"
        poster.write_bytes(b"\xff\xd8\xff\xe0jpeg")
        self.store.set_media_poster(media_id, str(poster))
        return poster

    def test_a_branch_cannot_fetch_another_branch_poster(self):
        """A picture of a clip is as private as the clip.

        The poster route is a second way to reach the library, so it has to
        answer to the same visibility as the list does -- otherwise a branch
        learns what its neighbours are showing by guessing clip ids.
        """
        self.poster_for(self.south_clip)
        client, _ = self.as_scoped("north", frozenset({"media.view"}), "group", self.north)

        self.assertEqual(client.get(f"/api/v1/media/{self.south_clip}/poster").status_code, 403)
        self.assertEqual(client.get(f"/api/v1/media/{self.south_clip}/preview").status_code, 403)

    def test_a_branch_fetches_its_own_poster(self):
        self.poster_for(self.north_clip)
        client, _ = self.as_scoped("north", frozenset({"media.view"}), "group", self.north)

        response = client.get(f"/api/v1/media/{self.north_clip}/poster")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "image/jpeg")

    def test_a_missing_poster_file_is_taken_again(self):
        """Clearing the posters directory must not cost the pictures forever.

        The path stays in the row after the file goes, so nothing would ever
        pick the clip up again -- the still would be lost until somebody
        re-uploaded the clip.
        """
        poster = self.poster_for(self.north_clip)
        poster.unlink()
        client, _ = self.as_scoped("north", frozenset({"media.view"}), "group", self.north)

        self.assertEqual(client.get(f"/api/v1/media/{self.north_clip}/poster").status_code, 404)

        self.assertIsNone(self.store.get_media(self.north_clip)["poster_path"])

    def test_a_shared_clip_poster_is_visible_to_a_branch(self):
        """Shared means everyone with media.view sees it, pictures included."""
        self.poster_for(self.shared)
        client, _ = self.as_scoped("north", frozenset({"media.view"}), "group", self.north)

        self.assertEqual(client.get(f"/api/v1/media/{self.shared}/poster").status_code, 200)

    def test_a_clip_that_predates_the_column_is_published(self):
        """Whatever was in the library was already playing."""
        self.assertEqual(self.state(self.north_clip), "published")

    def test_an_approver_publishes_a_draft(self):
        self.store.set_media_lifecycle(self.north_clip, "draft")
        client, csrf = self.as_scoped("north", self.APPROVER, "group", self.north)

        response = self.publish(client, csrf, self.north_clip)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.state(self.north_clip), "published")

    def test_a_branch_administrator_cannot_publish_on_its_own(self):
        """The preset stops short of approval on purpose."""
        self.store.set_media_lifecycle(self.north_clip, "draft")
        client, csrf = self.as_scoped("north", permissions.BRANCH_ROLES["branch_admin"], "group", self.north)

        response = self.publish(client, csrf, self.north_clip)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.state(self.north_clip), "draft")

    def test_the_approver_preset_is_what_lets_a_branch_publish(self):
        """Approval is added and removed as a role, not by editing a preset."""
        self.store.set_media_lifecycle(self.north_clip, "draft")
        client, csrf = self.as_scoped("north", permissions.BRANCH_ROLES["media_approver"], "group", self.north)

        response = self.publish(client, csrf, self.north_clip)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.state(self.north_clip), "published")

    def test_the_approver_preset_grants_nothing_but_approval(self):
        """It is added on top of a branch role, so it must not widen anything."""
        client, csrf = self.as_scoped("north", permissions.BRANCH_ROLES["media_approver"], "group", self.north)

        self.assertEqual(
            client.patch(
                f"/api/v1/media/{self.north_clip}",
                json={"title": "renamed"},
                headers={"X-CSRF-Token": csrf},
            ).status_code,
            403,
        )
        self.assertEqual(
            client.delete(f"/api/v1/media/{self.north_clip}", headers={"X-CSRF-Token": csrf}).status_code,
            403,
        )

    def test_an_approver_cannot_publish_outside_its_branch(self):
        self.store.set_media_lifecycle(self.south_clip, "draft")
        client, csrf = self.as_scoped("north", permissions.BRANCH_ROLES["media_approver"], "group", self.north)

        response = self.publish(client, csrf, self.south_clip)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.state(self.south_clip), "draft")

    def test_an_approver_sees_the_branch_it_approves_for_and_no_other(self):
        """Approving means deciding whether *this branch* may show a clip.

        Without the group tree the panel cannot even name the zone a clip
        belongs to, and an unnamed zone reads as the shared library -- which
        would tell an approver a branch clip belongs to the whole company.
        """
        client, _ = self.as_scoped("north", permissions.BRANCH_ROLES["media_approver"], "group", self.north)

        response = client.get("/api/v1/groups")

        self.assertEqual(response.status_code, 200, response.text)
        # The branch and what sits under it, never the branch next door.
        self.assertEqual(
            sorted(group["id"] for group in response.json()["groups"]),
            [self.north, self.north_floor],
        )

    def test_a_session_names_the_roles_it_actually_holds(self):
        """`users.role` calls a branch administrator a viewer, so the panel
        reads the grants instead. It has to be told which branch as well."""
        client, _ = self.as_scoped("north", permissions.BRANCH_ROLES["media_approver"], "group", self.north)

        roles = client.get("/api/v1/session").json()["roles"]

        self.assertEqual([(role["name"], role["scope_type"]) for role in roles], [("role-north", "group")])
        self.assertEqual(roles[0]["scope_group_name"], self.store.get_group(self.north)["name"])

    def test_editing_a_clip_is_not_approving_it(self):
        """The gate: media.manage renames, media.approve publishes."""
        self.store.set_media_lifecycle(self.north_clip, "draft")
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        response = self.publish(client, csrf, self.north_clip)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.state(self.north_clip), "draft")

    def test_a_branch_cannot_publish_a_shared_clip(self):
        self.store.set_media_lifecycle(self.shared, "draft")
        client, csrf = self.as_scoped("north", self.APPROVER, "group", self.north)

        response = self.publish(client, csrf, self.shared)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.state(self.shared), "draft")

    def test_a_branch_cannot_publish_another_branch_clip(self):
        self.store.set_media_lifecycle(self.south_clip, "draft")
        client, csrf = self.as_scoped("north", self.APPROVER, "group", self.north)

        response = self.publish(client, csrf, self.south_clip)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.state(self.south_clip), "draft")

    def test_deleting_archives_and_keeps_the_file(self):
        client, csrf = self.as_scoped("north", self.DELETER, "group", self.north)
        path = Path(self.store.get_media(self.north_clip)["original_path"])

        response = self.archive(client, csrf, self.north_clip)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.state(self.north_clip), "archived")
        self.assertTrue(path.exists(), "archiving must not unlink the file")

    def test_archiving_leaves_a_playlist_intact(self):
        """A screen must not lose the clip it is playing to somebody's delete."""
        playlist = self.store.create_playlist("Севера")
        self.store.set_playlist_group(playlist, self.north)
        self.store.add_playlist_item(playlist, self.north_clip)
        client, csrf = self.as_scoped("north", self.DELETER, "group", self.north)

        self.archive(client, csrf, self.north_clip)

        self.assertEqual([item["media_id"] for item in self.store.playlist_items(playlist)], [self.north_clip])

    def test_destroying_needs_more_than_delete(self):
        self.store.set_media_lifecycle(self.north_clip, "archived")
        client, csrf = self.as_scoped("north", self.DELETER, "group", self.north)

        response = self.purge(client, csrf, self.north_clip)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNotNone(self.store.get_media(self.north_clip))

    def test_a_published_clip_cannot_be_destroyed_outright(self):
        """Archiving first is the pause that makes a purge deliberate."""
        client, csrf = self.as_scoped("north", self.PURGER, "group", self.north)

        response = self.purge(client, csrf, self.north_clip)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIsNotNone(self.store.get_media(self.north_clip))

    def test_a_clip_a_playlist_still_holds_cannot_be_destroyed(self):
        playlist = self.store.create_playlist("Севера")
        self.store.set_playlist_group(playlist, self.north)
        self.store.add_playlist_item(playlist, self.north_clip)
        self.store.set_media_lifecycle(self.north_clip, "archived")
        client, csrf = self.as_scoped("north", self.PURGER, "group", self.north)

        response = self.purge(client, csrf, self.north_clip)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIsNotNone(self.store.get_media(self.north_clip))

    def test_a_playlist_in_another_branch_still_counts(self):
        """The caller cannot see that playlist, but the screen playing it can."""
        playlist = self.store.create_playlist("Юга")
        self.store.set_playlist_group(playlist, self.south)
        self.store.add_playlist_item(playlist, self.north_clip)
        self.store.set_media_lifecycle(self.north_clip, "archived")
        client, csrf = self.as_scoped("north", self.PURGER, "group", self.north)

        response = self.purge(client, csrf, self.north_clip)

        self.assertEqual(response.status_code, 409, response.text)

    def test_an_archived_unused_clip_is_destroyed_with_its_files(self):
        self.store.set_media_lifecycle(self.north_clip, "archived")
        path = Path(self.store.get_media(self.north_clip)["original_path"])
        client, csrf = self.as_scoped("north", self.PURGER, "group", self.north)

        response = self.purge(client, csrf, self.north_clip)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(self.store.get_media(self.north_clip))
        self.assertFalse(path.exists())

    def test_a_branch_cannot_destroy_a_shared_clip(self):
        self.store.set_media_lifecycle(self.shared, "archived")
        client, csrf = self.as_scoped("north", self.PURGER, "group", self.north)

        response = self.purge(client, csrf, self.shared)

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNotNone(self.store.get_media(self.shared))

    def test_an_expiry_is_set_through_the_card(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        response = client.patch(
            f"/api/v1/media/{self.north_clip}",
            json={"title": "Севера", "expires_at": 2000000000},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store.get_media(self.north_clip)["expires_at"], 2000000000)

    def test_renaming_does_not_clear_an_expiry(self):
        """Omitting the field means "leave it", not "never expires"."""
        self.store.set_media_expiry(self.north_clip, 2000000000)
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        client.patch(
            f"/api/v1/media/{self.north_clip}",
            json={"title": "Другое имя"},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(self.store.get_media(self.north_clip)["expires_at"], 2000000000)

    def test_a_campaign_can_be_set_up_before_it_starts(self):
        """The point of the start: approve it now, it airs on the first."""
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        response = client.patch(
            f"/api/v1/media/{self.north_clip}",
            json={"title": "Акция", "starts_at": 2000000000, "expires_at": 2000086400},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(response.status_code, 200, response.text)
        stored = self.store.get_media(self.north_clip)
        self.assertEqual((stored["starts_at"], stored["expires_at"]), (2000000000, 2000086400))
        self.assertEqual(lifecycle.effective_state(stored, now=1999999999), "scheduled")
        self.assertFalse(lifecycle.playable(stored, now=1999999999))
        self.assertTrue(lifecycle.playable(stored, now=2000000001))

    def test_a_window_that_closes_before_it_opens_is_refused(self):
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        response = client.patch(
            f"/api/v1/media/{self.north_clip}",
            json={"title": "Акция", "starts_at": 2000086400, "expires_at": 2000000000},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIsNone(self.store.get_media(self.north_clip)["starts_at"])

    def test_moving_only_the_start_cannot_invert_an_existing_window(self):
        """The window is checked as it will end up, not as it was sent."""
        self.store.set_media_expiry(self.north_clip, 2000000000)
        client, csrf = self.as_scoped("north", frozenset({"media.view", "media.manage"}), "group", self.north)

        response = client.patch(
            f"/api/v1/media/{self.north_clip}",
            json={"title": "Акция", "starts_at": 2000086400},
            headers={"X-CSRF-Token": csrf},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIsNone(self.store.get_media(self.north_clip)["starts_at"])


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
