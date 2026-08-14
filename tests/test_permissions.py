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
        text = source_text()
        used: set[str] = set()
        for call in re.findall(r"require_(?:any_)?permission\(([^)]*)\)", text):
            used |= set(re.findall(r'"([^"]+)"', call))
        used |= set(re.findall(r'has_permission\([^)]*?"([^"]+)"', text))
        self.assertTrue(used, "no permission checks found; the scan is broken")
        self.assertEqual(sorted(used - permissions.KEYS), [])

    def test_builtin_roles_only_contain_real_permissions(self):
        for name, granted in permissions.SEEDED_ROLES.items():
            with self.subTest(role=name):
                self.assertEqual(sorted(granted - permissions.KEYS), [])

    def test_branch_presets_hold_nothing_that_applies_installation_wide(self):
        """The whole point of a branch preset is that it is safe on a branch.

        A gate on a global-only key demands a global grant, and
        api_set_user_roles refuses to attach such a key to a group at all. One
        smuggled into a preset would therefore make it unusable for the single
        thing it exists for -- and, if the refusal were ever relaxed, would hand
        a branch authority over the whole installation.
        """
        for name, granted in permissions.BRANCH_ROLES.items():
            with self.subTest(role=name):
                self.assertEqual(sorted(granted & permissions.GLOBAL_ONLY), [])

    def test_branch_admin_contains_the_branch_operator(self):
        self.assertLess(permissions.BRANCH_ROLES["branch_operator"], permissions.BRANCH_ROLES["branch_admin"])

    def test_branch_presets_are_seeded_but_are_not_levels(self):
        """`users.role` still names a level; a branch preset needs a scope."""
        self.assertEqual(set(permissions.SEEDED_ROLES), set(permissions.BUILTIN_ROLES) | set(permissions.BRANCH_ROLES))
        self.assertEqual(set(permissions.BUILTIN_ROLES) & set(permissions.BRANCH_ROLES), set())
        for name in permissions.SEEDED_ROLES:
            with self.subTest(role=name):
                self.assertIn(name, permissions.BUILTIN_ROLE_DESCRIPTIONS)

    def test_every_role_that_manages_roles_can_also_read_them(self):
        """Splitting the read out of role.manage must not cost anybody access."""
        for name, granted in permissions.SEEDED_ROLES.items():
            with self.subTest(role=name):
                if "role.manage" in granted:
                    self.assertIn("role.view", granted)

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


class TranslationTests(unittest.TestCase):
    """The catalogue and the panel must not drift apart.

    A permission with no display string renders as its raw key or as untranslated
    English in a Russian panel, and the person building a role cannot tell what
    they are ticking. English descriptions are deliberately not duplicated into
    the frontend: `RolesView.vue` falls back to the text the API sent, which is
    the catalogue's own `description`, so that one is checked here instead.
    """

    I18N = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "src" / "i18n" / "index.js"

    @classmethod
    def setUpClass(cls):
        text = cls.I18N.read_text(encoding="utf-8")
        cls.locales = {}
        for locale in ("en", "ru"):
            start = text.index(f"\n  {locale}: {{\n")
            end = text.index("\n  },\n", start)
            cls.locales[locale] = set(re.findall(r"^\s{4}([A-Za-z0-9_]+):", text[start:end], re.MULTILINE))
        if not cls.locales["en"] or not cls.locales["ru"]:
            raise AssertionError("the i18n scan found no keys; it is broken")

    def test_the_catalogue_carries_its_own_english(self):
        for permission in permissions.CATALOG:
            with self.subTest(key=permission.key):
                self.assertTrue(permission.title.strip(), "missing title")
                self.assertTrue(permission.description.strip(), "missing description")

    def test_every_permission_has_a_label_in_every_locale(self):
        for locale, keys in self.locales.items():
            missing = [p.key for p in permissions.CATALOG if f"perm_{p.key.replace('.', '_')}" not in keys]
            with self.subTest(locale=locale):
                self.assertEqual(missing, [], f"permissions with no {locale} label in frontend/src/i18n")

    def test_every_permission_has_a_russian_description(self):
        missing = [p.key for p in permissions.CATALOG if f"perm_{p.key.replace('.', '_')}_desc" not in self.locales["ru"]]
        self.assertEqual(missing, [], "permissions with no Russian description in frontend/src/i18n")

    def test_every_shipped_role_has_a_name_and_a_hint_in_every_locale(self):
        for locale, keys in self.locales.items():
            for name in permissions.SEEDED_ROLES:
                with self.subTest(locale=locale, role=name):
                    self.assertIn(f"roleName_{name}", keys)
                    self.assertIn(f"builtinRoleHint_{name}", keys)

    def test_every_section_has_a_heading_in_every_locale(self):
        for locale, keys in self.locales.items():
            for section in permissions.sections():
                with self.subTest(locale=locale, section=section):
                    self.assertIn(f"permissionSection_{section}", keys)


class SeedingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = pathlib.Path(self._tmp.name) / "test.sqlite3"
        self.store = Store(self.path)

    def test_builtin_roles_exist_after_init(self):
        names = {role["name"] for role in self.store.list_roles()}
        self.assertEqual(names, set(permissions.SEEDED_ROLES))

    def test_builtin_roles_carry_the_catalogue_sets(self):
        for role in self.store.list_roles():
            with self.subTest(role=role["name"]):
                self.assertEqual(frozenset(role["permissions"]), permissions.SEEDED_ROLES[role["name"]])
                self.assertTrue(role["builtin"])

    def test_reseeding_a_branch_preset_does_not_duplicate_its_grants(self):
        """Seeding runs on every start, and an existing database is the case."""
        Store(self.path)
        reopened = Store(self.path)

        role = reopened.get_role_by_name("branch_admin")
        rows = reopened.rows("SELECT permission FROM role_permissions WHERE role_id = ?", (role["id"],))

        self.assertEqual(len(rows), len(permissions.BRANCH_ROLES["branch_admin"]))
        self.assertEqual(frozenset(role["permissions"]), permissions.BRANCH_ROLES["branch_admin"])
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
