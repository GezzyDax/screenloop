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
