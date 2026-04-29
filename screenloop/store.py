import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .config import DB_PATH


class Store:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_schema(self) -> None:
        with self._lock, closing(self.connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    checksum TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'uploaded',
                    transcoded_path TEXT,
                    duration_seconds INTEGER,
                    error TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transcode_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
                    profile TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    output_path TEXT,
                    error TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(media_id, profile)
                );

                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS playlist_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    UNIQUE(playlist_id, position)
                );

                CREATE TABLE IF NOT EXISTS tvs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    ip TEXT NOT NULL UNIQUE,
                    manufacturer TEXT,
                    model_name TEXT,
                    friendly_name TEXT,
                    profile TEXT NOT NULL DEFAULT 'generic_dlna',
                    control_url TEXT,
                    active_playlist_id INTEGER REFERENCES playlists(id) ON DELETE SET NULL,
                    current_index INTEGER NOT NULL DEFAULT 0,
                    current_media_id INTEGER REFERENCES media(id) ON DELETE SET NULL,
                    autoplay INTEGER NOT NULL DEFAULT 1,
                    repeat_mode TEXT NOT NULL DEFAULT 'all',
                    online INTEGER NOT NULL DEFAULT 0,
                    ping_reachable INTEGER NOT NULL DEFAULT 0,
                    dlna_reachable INTEGER NOT NULL DEFAULT 0,
                    soap_ready INTEGER NOT NULL DEFAULT 0,
                    streaming INTEGER NOT NULL DEFAULT 0,
                    playback_state TEXT NOT NULL DEFAULT 'UNKNOWN',
                    playback_started_at INTEGER,
                    last_replay_advance_at INTEGER,
                    last_seen INTEGER,
                    last_error TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tv_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tv_id INTEGER NOT NULL REFERENCES tvs(id) ON DELETE CASCADE,
                    command TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload_json TEXT,
                    error TEXT,
                    created_at INTEGER NOT NULL,
                    started_at INTEGER,
                    finished_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tv_id INTEGER REFERENCES tvs(id) ON DELETE SET NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT,
                    created_at INTEGER NOT NULL
                );
                """
            )
            self._ensure_column(conn, "transcode_jobs", "output_path", "TEXT")
            self._ensure_column(conn, "media", "duration_seconds", "INTEGER")
            self._ensure_column(conn, "tvs", "current_media_id", "INTEGER REFERENCES media(id) ON DELETE SET NULL")
            self._ensure_column(conn, "tvs", "playback_started_at", "INTEGER")
            self._ensure_column(conn, "tvs", "last_replay_advance_at", "INTEGER")
            self._ensure_column(conn, "tvs", "ping_reachable", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tvs", "dlna_reachable", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tvs", "soap_ready", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tvs", "streaming", "INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def row(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock, closing(self.connect()) as conn:
            item = conn.execute(sql, params).fetchone()
            return dict(item) if item else None

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock, closing(self.connect()) as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self._lock, closing(self.connect()) as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return int(cur.lastrowid or 0)

    def enqueue_command(self, tv_id: int, command: str, payload_json: str | None = None) -> int:
        now = int(time.time())
        if command in {"play_next", "rediscover"}:
            existing = self.row(
                """
                SELECT id FROM tv_commands
                WHERE tv_id = ? AND command = ? AND status IN ('pending', 'running')
                ORDER BY id DESC LIMIT 1
                """,
                (tv_id, command),
            )
            if existing:
                return int(existing["id"])
        command_id = self.execute(
            """
            INSERT INTO tv_commands (tv_id, command, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (tv_id, command, payload_json, now),
        )
        self.add_event(tv_id, "command_queued", f"Queued {command}", payload_json)
        return command_id

    def has_active_command(self, tv_id: int, command: str) -> bool:
        row = self.row(
            """
            SELECT id FROM tv_commands
            WHERE tv_id = ? AND command = ? AND status IN ('pending', 'running')
            LIMIT 1
            """,
            (tv_id, command),
        )
        return row is not None

    def next_pending_command(self) -> dict[str, Any] | None:
        return self.row(
            """
            SELECT c.*, t.name AS tv_name, t.ip AS tv_ip
            FROM tv_commands c
            JOIN tvs t ON t.id = c.tv_id
            WHERE c.status = 'pending'
              AND NOT EXISTS (
                SELECT 1 FROM tv_commands r
                WHERE r.tv_id = c.tv_id AND r.status = 'running'
              )
            ORDER BY c.created_at ASC, c.id ASC
            LIMIT 1
            """
        )

    def mark_command_running(self, command_id: int) -> None:
        self.execute(
            "UPDATE tv_commands SET status = 'running', started_at = ? WHERE id = ?",
            (int(time.time()), command_id),
        )

    def mark_command_done(self, command_id: int) -> None:
        self.execute(
            "UPDATE tv_commands SET status = 'done', error = NULL, finished_at = ? WHERE id = ?",
            (int(time.time()), command_id),
        )

    def mark_command_failed(self, command_id: int, error: str) -> None:
        self.execute(
            "UPDATE tv_commands SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
            (error, int(time.time()), command_id),
        )

    def recent_commands_for_tv(self, tv_id: int, limit: int = 5) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM tv_commands WHERE tv_id = ? ORDER BY id DESC LIMIT ?",
            (tv_id, limit),
        )

    def add_event(self, tv_id: int | None, event_type: str, message: str, details: str | None = None) -> int:
        event_id = self.execute(
            """
            INSERT INTO events (tv_id, event_type, message, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tv_id, event_type, message, details, int(time.time())),
        )
        self.execute(
            "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 1000)"
        )
        return event_id

    def list_events(self, tv_id: int | None = None, event_type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        where = []
        params: list[Any] = []
        if tv_id:
            where.append("e.tv_id = ?")
            params.append(tv_id)
        if event_type:
            where.append("e.event_type = ?")
            params.append(event_type)
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        params.append(limit)
        return self.rows(
            f"""
            SELECT e.*, t.name AS tv_name
            FROM events e
            LEFT JOIN tvs t ON t.id = e.tv_id
            {where_sql}
            ORDER BY e.id DESC
            LIMIT ?
            """,
            tuple(params),
        )

    def list_transcode_jobs(self) -> list[dict[str, Any]]:
        return self.rows(
            """
            SELECT j.*, m.title, m.original_name
            FROM transcode_jobs j
            JOIN media m ON m.id = j.media_id
            ORDER BY m.created_at DESC, j.profile
            """
        )

    def referenced_transcode_paths(self) -> set[str]:
        rows = self.rows("SELECT output_path FROM transcode_jobs WHERE output_path IS NOT NULL")
        return {str(row["output_path"]) for row in rows}

    def rebuild_transcode_job(self, job_id: int) -> None:
        self.execute(
            """
            UPDATE transcode_jobs
            SET status = 'pending', attempts = 0, output_path = NULL, error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (int(time.time()), job_id),
        )

    def add_media(
        self,
        title: str,
        original_path: Path,
        original_name: str,
        size: int,
        checksum: str,
        duration_seconds: int | None = None,
    ) -> int:
        now = int(time.time())
        return self.execute(
            """
            INSERT INTO media (title, original_path, original_name, size, checksum, duration_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, str(original_path), original_name, size, checksum, duration_seconds, now, now),
        )

    def list_media(self) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM media ORDER BY created_at DESC")

    def get_media(self, media_id: int) -> dict[str, Any] | None:
        return self.row("SELECT * FROM media WHERE id = ?", (media_id,))

    def next_media_missing_duration(self) -> dict[str, Any] | None:
        return self.row(
            """
            SELECT * FROM media
            WHERE duration_seconds IS NULL
            ORDER BY created_at ASC
            LIMIT 1
            """
        )

    def media_output_paths(self, media_id: int) -> list[str]:
        rows = self.rows(
            "SELECT output_path FROM transcode_jobs WHERE media_id = ? AND output_path IS NOT NULL",
            (media_id,),
        )
        return [str(row["output_path"]) for row in rows]

    def delete_media(self, media_id: int) -> None:
        self.execute("DELETE FROM media WHERE id = ?", (media_id,))

    def set_media_duration(self, media_id: int, duration_seconds: int) -> None:
        self.execute(
            "UPDATE media SET duration_seconds = ?, updated_at = ? WHERE id = ?",
            (duration_seconds, int(time.time()), media_id),
        )

    def ensure_transcode_job(self, media_id: int, profile: str) -> None:
        now = int(time.time())
        self.execute(
            """
            INSERT OR IGNORE INTO transcode_jobs (media_id, profile, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (media_id, profile, now, now),
        )

    def next_transcode_job(self) -> dict[str, Any] | None:
        return self.row(
            """
            SELECT j.*, m.original_path
            FROM transcode_jobs j
            JOIN media m ON m.id = j.media_id
            WHERE j.status IN ('pending', 'failed') AND j.attempts < 3
            ORDER BY j.created_at ASC
            LIMIT 1
            """
        )

    def mark_job_running(self, job_id: int) -> None:
        now = int(time.time())
        self.execute(
            "UPDATE transcode_jobs SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?",
            (now, job_id),
        )

    def mark_job_done(self, job_id: int, media_id: int, path: Path) -> None:
        now = int(time.time())
        with self._lock, closing(self.connect()) as conn:
            conn.execute(
                "UPDATE transcode_jobs SET status = 'done', output_path = ?, error = NULL, updated_at = ? WHERE id = ?",
                (str(path), now, job_id),
            )
            conn.execute(
                """
                UPDATE media
                SET status = 'ready', transcoded_path = ?, error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (str(path), now, media_id),
            )
            conn.commit()

    def mark_job_failed(self, job_id: int, media_id: int, error: str) -> None:
        now = int(time.time())
        with self._lock, closing(self.connect()) as conn:
            conn.execute(
                "UPDATE transcode_jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                (error, now, job_id),
            )
            conn.execute(
                "UPDATE media SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                (error, now, media_id),
            )
            conn.commit()

    def requeue_transcode_job(self, job_id: int) -> None:
        self.execute(
            """
            UPDATE transcode_jobs
            SET status = 'pending', attempts = 0, output_path = NULL, error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (int(time.time()), job_id),
        )

    def create_playlist(self, name: str) -> int:
        now = int(time.time())
        return self.execute("INSERT INTO playlists (name, created_at) VALUES (?, ?)", (name, now))

    def get_playlist(self, playlist_id: int) -> dict[str, Any] | None:
        return self.row("SELECT * FROM playlists WHERE id = ?", (playlist_id,))

    def delete_playlist(self, playlist_id: int) -> None:
        self.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))

    def list_playlists(self) -> list[dict[str, Any]]:
        return self.rows(
            """
            SELECT p.*, COUNT(i.id) AS item_count
            FROM playlists p
            LEFT JOIN playlist_items i ON i.playlist_id = p.id
            GROUP BY p.id
            ORDER BY p.name
            """
        )

    def playlist_items(self, playlist_id: int) -> list[dict[str, Any]]:
        return self.rows(
            """
            SELECT i.*, m.title, m.status, m.transcoded_path
            FROM playlist_items i
            JOIN media m ON m.id = i.media_id
            WHERE i.playlist_id = ?
            ORDER BY i.position
            """,
            (playlist_id,),
        )

    def get_transcode(self, media_id: int, profile: str) -> dict[str, Any] | None:
        return self.row(
            "SELECT * FROM transcode_jobs WHERE media_id = ? AND profile = ?",
            (media_id, profile),
        )

    def add_playlist_item(self, playlist_id: int, media_id: int) -> None:
        row = self.row("SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM playlist_items WHERE playlist_id = ?", (playlist_id,))
        position = int(row["next_pos"] if row else 0)
        self.execute(
            "INSERT INTO playlist_items (playlist_id, media_id, position) VALUES (?, ?, ?)",
            (playlist_id, media_id, position),
        )

    def remove_playlist_item(self, item_id: int) -> None:
        item = self.row("SELECT playlist_id FROM playlist_items WHERE id = ?", (item_id,))
        self.execute("DELETE FROM playlist_items WHERE id = ?", (item_id,))
        if item:
            self.compact_playlist_positions(int(item["playlist_id"]))

    def move_playlist_item(self, item_id: int, direction: str) -> None:
        item = self.row("SELECT * FROM playlist_items WHERE id = ?", (item_id,))
        if not item:
            return
        target_position = int(item["position"]) + (-1 if direction == "up" else 1)
        other = self.row(
            "SELECT * FROM playlist_items WHERE playlist_id = ? AND position = ?",
            (item["playlist_id"], target_position),
        )
        if not other:
            return
        with self._lock, closing(self.connect()) as conn:
            conn.execute("UPDATE playlist_items SET position = -1 WHERE id = ?", (item["id"],))
            conn.execute("UPDATE playlist_items SET position = ? WHERE id = ?", (item["position"], other["id"]))
            conn.execute("UPDATE playlist_items SET position = ? WHERE id = ?", (target_position, item["id"]))
            conn.commit()

    def compact_playlist_positions(self, playlist_id: int) -> None:
        rows = self.rows(
            "SELECT id FROM playlist_items WHERE playlist_id = ? ORDER BY position, id",
            (playlist_id,),
        )
        with self._lock, closing(self.connect()) as conn:
            for position, row in enumerate(rows):
                conn.execute("UPDATE playlist_items SET position = ? WHERE id = ?", (position, row["id"]))
            conn.commit()

    def add_tv(self, name: str, ip: str, profile: str) -> int:
        now = int(time.time())
        return self.execute(
            """
            INSERT INTO tvs (name, ip, profile, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, ip, profile, now, now),
        )

    def delete_tv(self, tv_id: int) -> None:
        self.execute("DELETE FROM tvs WHERE id = ?", (tv_id,))

    def list_tvs(self) -> list[dict[str, Any]]:
        return self.rows(
            """
            SELECT
                t.*,
                p.name AS playlist_name,
                current_media.title AS current_media_title,
                next_media.title AS next_media_title
            FROM tvs t
            LEFT JOIN playlists p ON p.id = t.active_playlist_id
            LEFT JOIN media current_media ON current_media.id = t.current_media_id
            LEFT JOIN playlist_items next_item
                ON next_item.playlist_id = t.active_playlist_id
                AND next_item.position = t.current_index
            LEFT JOIN media next_media ON next_media.id = next_item.media_id
            ORDER BY t.name
            """
        )

    def get_tv(self, tv_id: int) -> dict[str, Any] | None:
        return self.row("SELECT * FROM tvs WHERE id = ?", (tv_id,))

    def get_tv_by_ip(self, ip: str) -> dict[str, Any] | None:
        return self.row("SELECT * FROM tvs WHERE ip = ?", (ip,))

    def update_tv_config(
        self,
        tv_id: int,
        name: str,
        ip: str,
        profile: str,
        playlist_id: int | None,
        autoplay: bool,
        control_url: str | None = None,
    ) -> None:
        now = int(time.time())
        old = self.get_tv(tv_id)
        playlist_changed = old and old.get("active_playlist_id") != playlist_id
        if playlist_changed:
            self.execute(
                """
                UPDATE tvs
                SET name = ?, ip = ?, profile = ?, active_playlist_id = ?, current_index = 0,
                    current_media_id = NULL, playback_started_at = NULL, autoplay = ?,
                    control_url = NULLIF(?, ''), updated_at = ?
                WHERE id = ?
                """,
                (name, ip, profile, playlist_id, int(autoplay), control_url or "", now, tv_id),
            )
        else:
            self.execute(
                """
                UPDATE tvs
                SET name = ?, ip = ?, profile = ?, active_playlist_id = ?, autoplay = ?,
                    control_url = NULLIF(?, ''), updated_at = ?
                WHERE id = ?
                """,
                (name, ip, profile, playlist_id, int(autoplay), control_url or "", now, tv_id),
            )

    def set_tv_error(self, tv_id: int, error: str) -> None:
        self.execute(
            """
            UPDATE tvs
            SET online = 0, soap_ready = 0, streaming = 0,
                playback_state = 'ERROR', last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (error, int(time.time()), tv_id),
        )

    def clear_tv_control_url(self, tv_id: int, error: str | None = None) -> None:
        self.execute(
            """
            UPDATE tvs
            SET control_url = NULL, online = 0, dlna_reachable = 0, soap_ready = 0, streaming = 0,
                playback_state = 'OFFLINE',
                last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (error, int(time.time()), tv_id),
        )

    def update_tv_discovery(self, tv_id: int, info: dict[str, Any], profile: str) -> None:
        now = int(time.time())
        self.execute(
            """
            UPDATE tvs
            SET manufacturer = ?, model_name = ?, friendly_name = ?, control_url = ?,
                profile = ?, last_error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (
                info.get("manufacturer"),
                info.get("model_name"),
                info.get("friendly_name"),
                info.get("control_url"),
                profile,
                now,
                tv_id,
            ),
        )

    def update_tv_status(self, tv_id: int, online: bool, state: str, error: str | None = None) -> None:
        now = int(time.time())
        self.execute(
            """
            UPDATE tvs
            SET online = ?, soap_ready = ?, streaming = ?, playback_state = ?,
                last_seen = CASE WHEN ? THEN ? ELSE last_seen END,
                last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                int(online),
                int(online),
                int(state == "PLAYING"),
                state,
                int(online),
                now,
                error,
                now,
                tv_id,
            ),
        )

    def update_tv_health(
        self,
        tv_id: int,
        ping_reachable: bool | None = None,
        dlna_reachable: bool | None = None,
        soap_ready: bool | None = None,
        streaming: bool | None = None,
    ) -> None:
        updates = []
        params: list[Any] = []
        for column, value in (
            ("ping_reachable", ping_reachable),
            ("dlna_reachable", dlna_reachable),
            ("soap_ready", soap_ready),
            ("streaming", streaming),
        ):
            if value is not None:
                updates.append(f"{column} = ?")
                params.append(int(value))
        if not updates:
            return
        updates.append("updated_at = ?")
        params.append(int(time.time()))
        params.append(tv_id)
        self.execute(f"UPDATE tvs SET {', '.join(updates)} WHERE id = ?", tuple(params))

    def set_tv_playback_position(self, tv_id: int, index: int, media_id: int | None) -> None:
        now = int(time.time())
        self.execute(
            """
            UPDATE tvs
            SET current_index = ?, current_media_id = ?, playback_started_at = ?,
                last_replay_advance_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (index, media_id, now, now, tv_id),
        )

    def mark_tv_replay_advance(self, tv_id: int) -> None:
        self.execute(
            "UPDATE tvs SET last_replay_advance_at = ?, updated_at = ? WHERE id = ?",
            (int(time.time()), int(time.time()), tv_id),
        )

    def set_tv_control_url(self, tv_id: int, control_url: str) -> None:
        self.execute("UPDATE tvs SET control_url = ?, updated_at = ? WHERE id = ?", (control_url, int(time.time()), tv_id))
