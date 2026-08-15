"""Upgrade tests: databases created by older releases must still open today.

Fixtures under ``tests/fixtures/schema`` are logical dumps captured from
released versions (see ``scripts/schema_fixture.py``). Each one is replayed
into a fresh file, opened with the current ``Store``, and checked for both a
clean upgrade and intact data. This is the only automated guard against a
schema change that works on an empty database but destroys a production one.
"""

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from screenloop.store import Store

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "schema"

# Tables the application seeds for itself rather than tables that hold operator
# data. A release that adds a built-in role, or moves a permission between them,
# legitimately changes their row count on upgrade.
SEEDED_TABLES = {"roles", "role_permissions"}


def fixture_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.sql"))


def table_row_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
    finally:
        conn.close()


def grants(db_path: Path) -> set[tuple]:
    """Who holds what, where -- read raw, so it works before the upgrade too.

    Fixtures older than 2.6.0 predate the permission model entirely; they carry
    a role name on the user row and have no table to read, so they come back
    empty and the caller skips them.
    """
    conn = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"role_assignments", "role_permissions"} <= tables:
            return set()
        return {
            row
            for row in conn.execute(
                """
                SELECT u.username, rp.permission, a.scope_type, a.scope_id
                FROM role_assignments a
                JOIN users u ON u.id = a.user_id
                JOIN role_permissions rp ON rp.role_id = a.role_id
                """
            )
        }
    finally:
        conn.close()


def restore(fixture: Path, db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(fixture.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


class SchemaFixtureTests(unittest.TestCase):
    def test_fixtures_are_present(self):
        self.assertTrue(fixture_paths(), f"no schema fixtures found in {FIXTURE_DIR}")


class MigrationTests(unittest.TestCase):
    """Runs once per fixture, so a new release only needs a new .sql file."""

    def test_upgrade_keeps_every_row(self):
        for fixture in fixture_paths():
            with self.subTest(fixture=fixture.name), TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "screenloop.sqlite3"
                restore(fixture, db_path)
                before = table_row_counts(db_path)

                Store(db_path)

                after = table_row_counts(db_path)
                for table, count in before.items():
                    self.assertIn(table, after, f"{fixture.name}: table {table} disappeared on upgrade")
                    if table in SEEDED_TABLES:
                        # The app owns these: startup re-seeds the built-in roles
                        # and adds any that a release introduced, so they grow by
                        # design. What must never happen is losing rows, and
                        # test_nobody_loses_access_in_the_upgrade checks the part
                        # that actually matters -- that no grant got smaller.
                        self.assertGreaterEqual(
                            after[table],
                            count,
                            f"{fixture.name}: table {table} lost rows ({count} -> {after[table]})",
                        )
                        continue
                    self.assertEqual(
                        count,
                        after[table],
                        f"{fixture.name}: table {table} changed from {count} to {after[table]} rows",
                    )

    def test_upgrade_is_idempotent(self):
        for fixture in fixture_paths():
            with self.subTest(fixture=fixture.name), TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "screenloop.sqlite3"
                restore(fixture, db_path)

                Store(db_path)
                first = table_row_counts(db_path)
                Store(db_path)

                self.assertEqual(first, table_row_counts(db_path), f"{fixture.name}: reopening changed the data")

    def test_queries_run_against_an_upgraded_database(self):
        """A column added without a matching _ensure_column only fails here.

        The list queries are wide joins over most of the schema, so they break
        loudly if the upgrade path missed a column that the current code reads.
        """
        for fixture in fixture_paths():
            with self.subTest(fixture=fixture.name), TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "screenloop.sqlite3"
                restore(fixture, db_path)

                store = Store(db_path)

                self.assertTrue(store.list_tvs())
                self.assertTrue(store.list_media())
                self.assertTrue(store.list_playlists())
                self.assertTrue(store.list_transcode_jobs())
                store.list_nodes()
                store.list_events(limit=10)

    def test_existing_clips_are_published_by_the_upgrade(self):
        """Everything already in the library was already playing.

        The lifecycle column arrives with `published` as its default for
        exactly this reason: a draft state applied to old rows would silence
        every screen in the installation on upgrade.
        """
        for fixture in fixture_paths():
            with self.subTest(fixture=fixture.name), TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "screenloop.sqlite3"
                restore(fixture, db_path)

                store = Store(db_path)

                clips = store.list_media()
                self.assertTrue(clips, f"{fixture.name}: no clips to check")
                self.assertEqual({clip["lifecycle"] for clip in clips}, {"published"})
                self.assertEqual({clip["expires_at"] for clip in clips}, {None})

    def test_nobody_loses_access_in_the_upgrade(self):
        """Re-seeding the built-in roles must not quietly take authority away.

        Every release since 2.6.0 has rewritten the built-in role sets in
        place, and splitting a permission in two -- ``tv.move`` out of
        ``tv.manage`` -- is exactly the change that can shrink somebody's
        access without touching a single grant row. The scope has to survive
        as well: a grant on one group must not come out global, or the
        upgrade would hand a branch the whole installation.
        """
        for fixture in fixture_paths():
            with self.subTest(fixture=fixture.name), TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "screenloop.sqlite3"
                restore(fixture, db_path)
                before = grants(db_path)
                if not before:
                    continue

                Store(db_path)

                lost = before - grants(db_path)
                self.assertEqual(set(), lost, f"{fixture.name}: access lost in upgrade: {sorted(lost)}")

    def test_upgrade_adds_tables_the_fixture_predates(self):
        """Older fixtures must gain the tables introduced after their release."""
        for fixture in fixture_paths():
            with self.subTest(fixture=fixture.name), TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "screenloop.sqlite3"
                restore(fixture, db_path)

                Store(db_path)

                tables = set(table_row_counts(db_path))
                self.assertTrue({"media", "playlists", "tvs", "users", "nodes"} <= tables, f"{fixture.name}: {tables}")


if __name__ == "__main__":
    unittest.main()
