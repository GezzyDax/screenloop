"""Permission engine: catalogue integrity, faithful migration, no escalation.

The engine replaced an integer role comparison. Two things must hold: nobody's
access changed, and permissions composing must not become a way to acquire
authority you were not given.
"""

import pathlib
import re
import unittest
from tempfile import TemporaryDirectory

from screenloop import permissions
from screenloop.store import Store

SOURCE_DIR = pathlib.Path(__file__).resolve().parent.parent / "screenloop"


def source_text() -> str:
    return "\n".join(path.read_text() for path in sorted(SOURCE_DIR.glob("*.py")) if path.name != "permissions.py")


class CatalogueTests(unittest.TestCase):
    def test_keys_are_unique(self):
        keys = [permission.key for permission in permissions.CATALOG]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_permission_is_actually_checked_somewhere(self):
        """A permission no code checks is rubbish nobody can discover."""
        text = source_text()
        unused = [key for key in sorted(permissions.KEYS) if f'"{key}"' not in text]
        self.assertEqual(unused, [], "catalogue entries that no gate or helper checks")

    def test_every_checked_permission_exists_in_the_catalogue(self):
        """A gate naming a permission nothing defines denies everybody, silently."""
        used = set(re.findall(r'require_permission\(\s*"([^"]+)"', source_text()))
        used |= set(re.findall(r'has_permission\([^)]*?"([^"]+)"', source_text()))
        self.assertTrue(used, "no permission checks found; the scan is broken")
        self.assertEqual(sorted(used - permissions.KEYS), [])

    def test_builtin_roles_only_contain_real_permissions(self):
        for name, granted in permissions.BUILTIN_ROLES.items():
            with self.subTest(role=name):
                self.assertEqual(sorted(granted - permissions.KEYS), [])

    def test_builtin_roles_are_nested(self):
        """Viewer < operator < admin, the ladder the old integers encoded."""
        self.assertLess(permissions.BUILTIN_ROLES["viewer"], permissions.BUILTIN_ROLES["operator"])
        self.assertLess(permissions.BUILTIN_ROLES["operator"], permissions.BUILTIN_ROLES["admin"])

    def test_admin_holds_everything(self):
        self.assertEqual(permissions.BUILTIN_ROLES["admin"], permissions.KEYS)

    def test_an_operator_can_still_make_an_upload_play(self):
        """Uploads now land as drafts. An operator could always upload a clip
        and have it play, so taking approval away would change what a built-in
        role can do -- the one thing these roles exist to prevent."""
        operator = permissions.BUILTIN_ROLES["operator"]
        self.assertLessEqual({"media.upload", "media.approve"}, operator)

    def test_an_operator_still_cannot_destroy_a_clip(self):
        """Removing files was admin-only: an operator never held media.delete."""
        operator = permissions.BUILTIN_ROLES["operator"]
        self.assertNotIn("media.delete", operator)
        self.assertNotIn("media.purge", operator)

    def test_the_lifecycle_permissions_are_scoped(self):
        """A branch approves its own clips; neither is an installation-wide act."""
        self.assertNotIn("media.approve", permissions.GLOBAL_ONLY)
        self.assertNotIn("media.purge", permissions.GLOBAL_ONLY)

    def test_derived_role_reports_the_strongest_match(self):
        self.assertEqual(permissions.derived_role(permissions.KEYS), "admin")
        self.assertEqual(permissions.derived_role(permissions.BUILTIN_ROLES["operator"]), "operator")
        self.assertEqual(permissions.derived_role(permissions.BUILTIN_ROLES["viewer"]), "viewer")
        self.assertEqual(permissions.derived_role(frozenset()), "viewer")

    def test_normalise_drops_permissions_that_no_longer_exist(self):
        """Grants are rows and rows outlive code."""
        self.assertEqual(permissions.normalise(["tv.view", "removed.in.a.later.release"]), frozenset({"tv.view"}))
        self.assertEqual(permissions.normalise(None), frozenset())


class SeedingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = pathlib.Path(self._tmp.name) / "test.sqlite3"
        self.store = Store(self.path)

    def test_builtin_roles_exist_after_init(self):
        names = {role["name"] for role in self.store.list_roles()}
        self.assertEqual(names, set(permissions.BUILTIN_ROLES))

    def test_builtin_roles_carry_the_catalogue_sets(self):
        for role in self.store.list_roles():
            with self.subTest(role=role["name"]):
                self.assertEqual(frozenset(role["permissions"]), permissions.BUILTIN_ROLES[role["name"]])
                self.assertTrue(role["builtin"])

    def test_a_new_user_gets_the_grants_for_their_role(self):
        for role in ("viewer", "operator", "admin"):
            with self.subTest(role=role):
                user_id = self.store.create_user(f"u-{role}", "password-1234", role)
                self.assertEqual(self.store.user_permissions(user_id), permissions.BUILTIN_ROLES[role])

    def test_changing_a_users_role_moves_their_grants(self):
        user_id = self.store.create_user("mover", "password-1234", "viewer")
        self.store.update_user(user_id, "operator", False)
        self.assertEqual(self.store.user_permissions(user_id), permissions.BUILTIN_ROLES["operator"])

    def test_reopening_the_database_is_idempotent(self):
        user_id = self.store.create_user("stable", "password-1234", "operator")
        before = {role["name"] for role in self.store.list_roles()}
        reopened = Store(self.path)
        self.assertEqual({role["name"] for role in reopened.list_roles()}, before)
        self.assertEqual(reopened.user_permissions(user_id), permissions.BUILTIN_ROLES["operator"])

    def test_reopening_does_not_reset_deliberately_changed_grants(self):
        """A restart must not undo an administrator's decision."""
        user_id = self.store.create_user("special", "password-1234", "operator")
        viewer = self.store.get_role_by_name("viewer")
        self.store.set_user_roles(user_id, [{"role_id": int(viewer["id"]), "scope_type": "global", "scope_id": None}])

        reopened = Store(self.path)

        self.assertEqual(reopened.user_permissions(user_id), permissions.BUILTIN_ROLES["viewer"])

    def test_a_release_adding_a_permission_grants_it_to_admins(self):
        """Built-in sets are rewritten from the catalogue on every start."""
        admin = self.store.get_role_by_name("admin")
        self.store.execute("DELETE FROM role_permissions WHERE role_id = ? AND permission = ?", (admin["id"], "tv.scan"))
        self.assertNotIn("tv.scan", self.store.role_permissions(int(admin["id"])))

        reopened = Store(self.path)

        self.assertIn("tv.scan", reopened.role_permissions(int(admin["id"])))

    def test_a_stale_permission_on_a_builtin_role_is_swept_up(self):
        admin = self.store.get_role_by_name("admin")
        self.store.execute(
            "INSERT INTO role_permissions (role_id, permission) VALUES (?, ?)",
            (admin["id"], "invented.permission"),
        )

        reopened = Store(self.path)

        self.assertNotIn("invented.permission", reopened.role_permissions(int(admin["id"])))

    def test_a_custom_role_is_never_touched_by_seeding(self):
        role_id = self.store.create_role("Signage", "", frozenset({"tv.view", "tv.command"}))
        reopened = Store(self.path)
        self.assertEqual(reopened.role_permissions(role_id), frozenset({"tv.view", "tv.command"}))
        self.assertFalse(reopened.get_role(role_id)["builtin"])


class AuthorityAccountingTests(SeedingTests):
    def test_permissions_come_from_every_role_a_user_holds(self):
        user_id = self.store.create_user("multi", "password-1234", "viewer")
        commander = self.store.create_role("Commander", "", frozenset({"tv.command"}))
        viewer = self.store.get_role_by_name("viewer")
        self.store.set_user_roles(user_id, [{"role_id": int(viewer["id"])}, {"role_id": commander}])

        self.assertEqual(
            self.store.user_permissions(user_id),
            permissions.BUILTIN_ROLES["viewer"] | {"tv.command"},
        )

    def test_disabled_users_do_not_count_as_holders(self):
        """Otherwise a disabled admin would satisfy the last-admin check."""
        user_id = self.store.create_user("ghost", "password-1234", "admin")
        self.assertIn(user_id, self.store.users_with_permission("role.manage"))

        self.store.update_user(user_id, "admin", True)

        self.assertNotIn(user_id, self.store.users_with_permission("role.manage"))

    def test_excluding_a_role_reports_who_would_still_hold_the_permission(self):
        admin_role = self.store.get_role_by_name("admin")
        admin_id = self.store.create_user("boss", "password-1234", "admin")

        self.assertEqual(self.store.users_with_permission_excluding_role("role.manage", int(admin_role["id"])), [])

        spare = self.store.create_role("Spare", "", frozenset({"role.manage"}))
        other = self.store.create_user("deputy", "password-1234", "viewer")
        self.store.set_user_roles(other, [{"role_id": spare}])

        remaining = self.store.users_with_permission_excluding_role("role.manage", int(admin_role["id"]))
        self.assertEqual(remaining, [other])
        self.assertNotIn(admin_id, remaining)


if __name__ == "__main__":
    unittest.main()
