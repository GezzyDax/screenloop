"""Capture the current database schema, with sample rows, as a test fixture.

The upgrade tests in ``tests/test_migrations.py`` replay these fixtures through
today's ``Store.init_schema`` to prove that a database created by an older
release still upgrades cleanly and keeps its rows. Generate one per release:

    git worktree add /tmp/screenloop-v2.2.0 v2.2.0
    cd /tmp/screenloop-v2.2.0
    PYTHONPATH=. /path/to/.venv/bin/python scripts/schema_fixture.py \\
        /path/to/repo/tests/fixtures/schema/v2.2.0.sql

Seeding is deliberately schema-driven rather than hand-written: it introspects
whatever tables the checked-out release happens to have, so the same script
works against versions that predate it.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROWS_PER_TABLE = 2


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return sorted(row[0] for row in rows)


def foreign_key_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[3] for row in conn.execute(f"PRAGMA foreign_key_list('{table}')")}


def sample_value(table: str, column: str, decl_type: str, index: int, is_fk: bool):
    if is_fk:
        # Point at the first row of the parent table, which this script always
        # creates with rowid 1.
        return 1
    if "INT" in decl_type.upper():
        return index
    return f"{table}-{column}-{index}"


def seed(conn: sqlite3.Connection, table: str) -> bool:
    """Insert sample rows into one table. Returns False if it is not ready yet."""
    info = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    fks = foreign_key_columns(conn, table)
    columns: list[tuple[str, str, bool]] = []
    for _cid, name, decl_type, not_null, default, pk in info:
        if pk and "INT" in (decl_type or "").upper():
            continue  # autoincrement rowid
        if not not_null:
            continue  # nullable columns stay NULL; that is the interesting case
        if default is not None:
            continue
        columns.append((name, decl_type or "", name in fks))

    if not columns:
        return True

    names = ", ".join(f'"{name}"' for name, _, _ in columns)
    placeholders = ", ".join("?" for _ in columns)
    for index in range(1, ROWS_PER_TABLE + 1):
        values = [sample_value(table, name, decl, index, is_fk) for name, decl, is_fk in columns]
        try:
            conn.execute(f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})', values)
        except sqlite3.IntegrityError:
            # A foreign key parent has not been seeded yet, or a unique
            # constraint the generic strategy cannot satisfy. Retried by the
            # caller; genuinely unseedable tables are simply left empty.
            conn.rollback()
            return False
    conn.commit()
    return True


def seed_all(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        pending = table_names(conn)
        # Repeat passes so tables whose foreign key parents come later
        # alphabetically still get filled.
        for _ in range(len(pending) + 1):
            if not pending:
                break
            pending = [table for table in pending if not seed(conn, table)]
        for table in pending:
            print(f"note: left {table} empty, generic seeding could not satisfy it", file=sys.stderr)
    finally:
        conn.close()


def dump(db_path: Path, out_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as handle:
            for line in conn.iterdump():
                # WAL bookkeeping is per-file state, not schema; skip it so the
                # fixture stays a pure logical dump.
                if line.startswith("PRAGMA"):
                    continue
                handle.write(f"{line}\n")
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    out_path = Path(argv[1]).resolve()

    from screenloop.store import Store  # imported late so --help works without deps

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "screenloop.sqlite3"
        Store(db_path)
        seed_all(db_path)
        dump(db_path, out_path)

    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
