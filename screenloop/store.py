import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from . import lifecycle, permissions
from .config import DB_PATH, SESSION_MAX_LIFETIME_SECONDS, SESSION_TTL_SECONDS
from .security import create_session_token, hash_password, token_hash, verify_password

GroupScheduleValues = tuple[str, str | None, str | None, str | None]


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
                    silent INTEGER NOT NULL DEFAULT 0,
                    compressed INTEGER NOT NULL DEFAULT 0,
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

                CREATE TABLE IF NOT EXISTS tv_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    parent_id INTEGER REFERENCES tv_groups(id) ON DELETE CASCADE,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS tv_groups_unique_child
                    ON tv_groups(parent_id, name) WHERE parent_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS tv_groups_unique_root
                    ON tv_groups(name) WHERE parent_id IS NULL;

                CREATE TABLE IF NOT EXISTS tvs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    ip TEXT NOT NULL UNIQUE,
                    manufacturer TEXT,
                    model_name TEXT,
                    friendly_name TEXT,
                    profile TEXT NOT NULL DEFAULT 'generic_dlna',
                    control_url TEXT,
                    rendering_control_url TEXT,
                    active_playlist_id INTEGER REFERENCES playlists(id) ON DELETE SET NULL,
                    current_index INTEGER NOT NULL DEFAULT 0,
                    current_media_id INTEGER REFERENCES media(id) ON DELETE SET NULL,
                    autoplay INTEGER NOT NULL DEFAULT 1,
                    muted INTEGER NOT NULL DEFAULT 0,
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

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    ip TEXT,
                    user_agent TEXT,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    builtin INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS role_permissions (
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    permission TEXT NOT NULL,
                    PRIMARY KEY (role_id, permission)
                );

                -- Uniqueness lives in the indexes below rather than here: the
                -- same role granted on two branches is two rows, and SQLite
                -- counts NULL scope_ids as distinct, so a plain UNIQUE over the
                -- four columns would let a global grant be handed out twice.
                CREATE TABLE IF NOT EXISTS role_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    created_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS role_assignments_user ON role_assignments(user_id);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    token_hash TEXT UNIQUE,
                    enroll_token_hash TEXT UNIQUE,
                    enroll_expires_at INTEGER,
                    version TEXT,
                    hostname TEXT,
                    online INTEGER NOT NULL DEFAULT 0,
                    last_seen INTEGER,
                    cache_used_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                """
            )
            self._ensure_column(conn, "transcode_jobs", "output_path", "TEXT")
            self._ensure_column(conn, "media", "duration_seconds", "INTEGER")
            self._ensure_column(conn, "media", "silent", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "media", "compressed", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tvs", "current_media_id", "INTEGER REFERENCES media(id) ON DELETE SET NULL")
            self._ensure_column(conn, "tvs", "playback_started_at", "INTEGER")
            self._ensure_column(conn, "tvs", "last_replay_advance_at", "INTEGER")
            self._ensure_column(conn, "tvs", "ping_reachable", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tvs", "dlna_reachable", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tvs", "soap_ready", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tvs", "streaming", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tvs", "rendering_control_url", "TEXT")
            self._ensure_column(conn, "tvs", "muted", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "users", "disabled", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "tvs", "node_id", "INTEGER REFERENCES nodes(id) ON DELETE SET NULL")
            self._ensure_column(conn, "tvs", "group_id", "INTEGER REFERENCES tv_groups(id) ON DELETE SET NULL")
            # Operating hours. 'inherit' follows the global schedule, 'always'
            # opts a screen out of it, 'custom' uses the columns below. The
            # default keeps every existing TV on the previous behaviour.
            self._ensure_column(conn, "tvs", "schedule_mode", "TEXT NOT NULL DEFAULT 'inherit'")
            self._ensure_column(conn, "tvs", "schedule_days", "TEXT")
            self._ensure_column(conn, "tvs", "schedule_start", "TEXT")
            self._ensure_column(conn, "tvs", "schedule_end", "TEXT")
            self._ensure_column(conn, "tv_groups", "schedule_mode", "TEXT NOT NULL DEFAULT 'inherit'")
            self._ensure_column(conn, "tv_groups", "schedule_days", "TEXT")
            self._ensure_column(conn, "tv_groups", "schedule_start", "TEXT")
            self._ensure_column(conn, "tv_groups", "schedule_end", "TEXT")
            # Set when a screen was switched off at the panel rather than by us,
            # so the poll loop stops pushing it back on.
            self._ensure_column(conn, "tvs", "playback_suspended_at", "INTEGER")
            self._ensure_column(conn, "tvs", "playback_suspended_reason", "TEXT")
            # A grant used to apply everywhere. It can now be narrowed to a
            # group (covering that group and its subtree) or to a node. The
            # default keeps every existing grant global, so nobody's access
            # changes on upgrade.
            # A clip or playlist with no group is shared: everybody who may look
            # at the library sees it, but only a holder of a company-wide grant
            # may change or remove it. Existing rows get NULL, so nothing that
            # anyone could see before becomes invisible on upgrade.
            self._ensure_column(conn, "media", "group_id", "INTEGER REFERENCES tv_groups(id) ON DELETE SET NULL")
            self._ensure_column(conn, "media", "description", "TEXT")
            # Draft -> published -> archived, kept apart from `media.status`,
            # which is the transcode state. Existing rows default to
            # `published`: every clip in a database written before this column
            # was already playing, and an upgrade must not silence a screen.
            self._ensure_column(conn, "media", "lifecycle", f"TEXT NOT NULL DEFAULT '{lifecycle.DEFAULT}'")
            # Optional. NULL means the clip never expires, which is what every
            # existing clip was.
            self._ensure_column(conn, "media", "expires_at", "INTEGER")
            # The other half of the airing window. NULL means "as soon as it is
            # published", which is what every clip written before this column
            # was, so an upgrade changes nothing about what is on the screens.
            self._ensure_column(conn, "media", "starts_at", "INTEGER")
            # NULL means "no still taken yet" and the worker picks the row up;
            # an empty string means "tried and failed", which stops the backfill
            # retrying a broken file on every pass forever. Existing rows arrive
            # as NULL, so an upgrade fills in the whole library by itself.
            self._ensure_column(conn, "media", "poster_path", "TEXT")
            self._ensure_column(conn, "playlists", "group_id", "INTEGER REFERENCES tv_groups(id) ON DELETE SET NULL")
            self._ensure_column(conn, "role_assignments", "scope_type", "TEXT NOT NULL DEFAULT 'global'")
            self._ensure_column(conn, "role_assignments", "scope_id", "INTEGER")
            self._widen_role_assignment_key(conn)
            self._seed_builtin_roles(conn)
            conn.commit()

    NODE_ENROLL_TTL_SECONDS = 24 * 60 * 60

    def create_node(self, name: str) -> tuple[int, str]:
        enroll_token = create_session_token()
        now = int(time.time())
        node_id = self.execute(
            """
            INSERT INTO nodes (name, enroll_token_hash, enroll_expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name.strip(), token_hash(enroll_token), now + self.NODE_ENROLL_TTL_SECONDS, now, now),
        )
        return node_id, enroll_token

    def list_nodes(self) -> list[dict[str, Any]]:
        return self.rows(
            """
            SELECT n.id, n.name, n.version, n.hostname, n.online, n.last_seen,
                   n.cache_used_bytes, n.created_at, n.updated_at,
                   n.token_hash IS NOT NULL AS enrolled,
                   (SELECT COUNT(*) FROM tvs t WHERE t.node_id = n.id) AS tv_count
            FROM nodes n
            ORDER BY n.name
            """
        )

    def get_node(self, node_id: int) -> dict[str, Any] | None:
        return self.row("SELECT * FROM nodes WHERE id = ?", (node_id,))

    def rename_node(self, node_id: int, name: str) -> None:
        self.execute("UPDATE nodes SET name = ?, updated_at = ? WHERE id = ?", (name.strip(), int(time.time()), node_id))

    def delete_node(self, node_id: int) -> None:
        self.execute("UPDATE tvs SET node_id = NULL WHERE node_id = ?", (node_id,))
        self.execute("DELETE FROM nodes WHERE id = ?", (node_id,))

    def claim_node_enrollment(self, enroll_token: str) -> dict[str, Any] | None:
        now = int(time.time())
        row = self.row(
            """
            SELECT * FROM nodes
            WHERE enroll_token_hash = ? AND token_hash IS NULL AND enroll_expires_at >= ?
            """,
            (token_hash(enroll_token), now),
        )
        if not row:
            return None
        node_token = create_session_token()
        self.execute(
            """
            UPDATE nodes
            SET token_hash = ?, enroll_token_hash = NULL, enroll_expires_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (token_hash(node_token), now, row["id"]),
        )
        return {"node_id": row["id"], "name": row["name"], "token": node_token}

    def get_node_by_token(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        return self.row("SELECT * FROM nodes WHERE token_hash = ?", (token_hash(token),))

    def set_node_runtime(
        self,
        node_id: int,
        online: bool | None = None,
        version: str | None = None,
        hostname: str | None = None,
        cache_used_bytes: int | None = None,
    ) -> None:
        updates = ["last_seen = ?", "updated_at = ?"]
        now = int(time.time())
        params: list[Any] = [now, now]
        fields = (
            ("online", None if online is None else int(online)),
            ("version", version),
            ("hostname", hostname),
            ("cache_used_bytes", cache_used_bytes),
        )
        for column, value in fields:
            if value is not None:
                updates.append(f"{column} = ?")
                params.append(value)
        params.append(node_id)
        self.execute(f"UPDATE nodes SET {', '.join(updates)} WHERE id = ?", tuple(params))

    def mark_all_nodes_offline(self) -> None:
        self.execute("UPDATE nodes SET online = 0, updated_at = ? WHERE online = 1", (int(time.time()),))

    def set_tv_node(self, tv_id: int, node_id: int | None) -> None:
        self.execute("UPDATE tvs SET node_id = ?, updated_at = ? WHERE id = ?", (node_id, int(time.time()), tv_id))

    def set_tv_group(self, tv_id: int, group_id: int | None) -> None:
        self.execute("UPDATE tvs SET group_id = ?, updated_at = ? WHERE id = ?", (group_id, int(time.time()), tv_id))

    def tvs_for_node(self, node_id: int) -> list[dict[str, Any]]:
        return self._with_group_schedule_chains(
            self.rows("SELECT * FROM tvs WHERE node_id = ? ORDER BY name", (node_id,))
        )

    def mark_node_tvs_unreachable(self, node_id: int) -> None:
        self.execute(
            """
            UPDATE tvs
            SET online = 0, ping_reachable = 0, dlna_reachable = 0,
                soap_ready = 0, streaming = 0, playback_state = 'OFFLINE', updated_at = ?
            WHERE node_id = ?
            """,
            (int(time.time()), node_id),
        )

    def apply_node_tv_status(self, node_id: int, status: dict[str, Any]) -> bool:
        tv = self.get_tv(int(status.get("tv_id") or 0))
        if not tv or tv.get("node_id") != node_id:
            return False
        now = int(time.time())
        online = bool(status.get("online"))
        self.execute(
            """
            UPDATE tvs
            SET online = ?, ping_reachable = ?, dlna_reachable = ?, soap_ready = ?, streaming = ?,
                playback_state = ?, current_media_id = ?, current_index = ?,
                playback_started_at = ?,
                last_seen = CASE WHEN ? THEN ? ELSE last_seen END,
                last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                int(online),
                int(bool(status.get("ping_reachable", online))),
                int(bool(status.get("dlna_reachable", online))),
                int(bool(status.get("soap_ready", online))),
                int(bool(status.get("streaming"))),
                str(status.get("state") or "UNKNOWN"),
                status.get("current_media_id"),
                int(status.get("current_index") or 0),
                status.get("playback_started_at"),
                int(online),
                now,
                status.get("last_error"),
                now,
                tv["id"],
            ),
        )
        return True

    def fail_stale_running_commands(self, older_than_seconds: int = 120) -> int:
        cutoff = int(time.time()) - older_than_seconds
        commands = self.rows(
            "SELECT id, tv_id, command FROM tv_commands WHERE status = 'running' AND started_at IS NOT NULL AND started_at < ?",
            (cutoff,),
        )
        for command in commands:
            self.mark_command_failed(command["id"], "Command timed out")
            self.add_event(command["tv_id"], "command_failed", f"{command['command']} timed out")
        return len(commands)

    def user_count(self) -> int:
        row = self.row("SELECT COUNT(*) AS count FROM users")
        return int(row["count"] if row else 0)

    def ensure_bootstrap_admin(self, username: str, password: str) -> int | None:
        if self.user_count() > 0:
            return None
        return self.create_user(username, password, "admin")

    def create_user(self, username: str, password: str, role: str) -> int:
        role = role if role in permissions.BUILTIN_ROLES else "viewer"
        now = int(time.time())
        user_id = self.execute(
            """
            INSERT INTO users (username, password_hash, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username.strip(), hash_password(password), role, now, now),
        )
        self.grant_builtin_role(user_id, role)
        return user_id

    def grant_builtin_role(self, user_id: int, role: str) -> None:
        """Replace a user's roles with the single built-in role named.

        `users.role` remains the source of truth for the three shipped roles, so
        creating or re-roling a user has to keep the grants in step. Custom
        roles are attached separately through set_user_roles.
        """
        row = self.row("SELECT id FROM roles WHERE name = ? AND builtin = 1", (role,))
        if not row:
            return
        self.set_user_roles(user_id, [{"role_id": int(row["id"]), "scope_type": "global", "scope_id": None}])

    def list_users(self) -> list[dict[str, Any]]:
        users = self.rows("SELECT id, username, role, disabled, created_at, updated_at FROM users ORDER BY username")
        for user in users:
            user["roles"] = self.user_roles(int(user["id"]))
            user["permissions"] = sorted(self.user_permissions(int(user["id"])))
        return users

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        return self.row("SELECT id, username, role, disabled, created_at, updated_at FROM users WHERE id = ?", (user_id,))

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        return self.row("SELECT * FROM users WHERE username = ?", (username.strip(),))

    def authenticate_user(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.get_user_by_username(username)
        if not user or user.get("disabled"):
            return None
        if not verify_password(password, user.get("password_hash")):
            return None
        # The login response reports what the caller may do, so the row has to
        # carry its grants exactly as a session-loaded one does.
        user["permissions"] = self.user_permissions(int(user["id"]))
        return user

    def update_user(self, user_id: int, role: str, disabled: bool) -> None:
        role = role if role in permissions.BUILTIN_ROLES else "viewer"
        previous = self.get_user(user_id)
        self.execute(
            "UPDATE users SET role = ?, disabled = ?, updated_at = ? WHERE id = ?",
            (role, int(disabled), int(time.time()), user_id),
        )
        if not previous or previous.get("role") != role:
            self.grant_builtin_role(user_id, role)

    def set_user_password(self, user_id: int, password: str, keep_token: str | None = None) -> None:
        self.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hash_password(password), int(time.time()), user_id),
        )
        if keep_token:
            self.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                (user_id, token_hash(keep_token)),
            )
        else:
            self.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def count_active_admins(self, exclude_user_id: int | None = None) -> int:
        if exclude_user_id is None:
            row = self.row("SELECT COUNT(*) AS count FROM users WHERE role = 'admin' AND disabled = 0")
        else:
            row = self.row(
                "SELECT COUNT(*) AS count FROM users WHERE role = 'admin' AND disabled = 0 AND id != ?",
                (exclude_user_id,),
            )
        return int(row["count"] if row else 0)

    def create_session(self, user_id: int, ip: str, user_agent: str) -> str:
        now = int(time.time())
        token = create_session_token()
        self.execute(
            """
            INSERT INTO sessions (user_id, token_hash, ip, user_agent, expires_at, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, token_hash(token), ip, user_agent[:500], now + SESSION_TTL_SECONDS, now, now),
        )
        return token

    def get_session_user(self, token: str | None, touch: bool = True) -> dict[str, Any] | None:
        if not token:
            return None
        now = int(time.time())
        row = self.row(
            """
            SELECT s.id AS session_id, s.expires_at, s.created_at AS session_created_at,
                   u.id, u.username, u.role, u.disabled
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash(token),),
        )
        if not row or row.get("disabled") or int(row["expires_at"]) < now:
            self.delete_session(token)
            return None
        if touch:
            # Sliding renewal capped by an absolute session lifetime.
            expires_at = min(now + SESSION_TTL_SECONDS, int(row["session_created_at"]) + SESSION_MAX_LIFETIME_SECONDS)
            self.execute(
                "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE id = ?",
                (now, max(expires_at, int(row["expires_at"])), row["session_id"]),
            )
        # Read per request rather than cached in the session row, so revoking a
        # role takes effect on the user's very next call instead of whenever
        # they happen to log in again.
        row["permissions"] = self.user_permissions(int(row["id"]))
        return row

    def user_permissions(self, user_id: int) -> frozenset[str]:
        """Every permission a user holds anywhere, ignoring scope.

        Used where the question is "may this person do this at all" -- the
        panel's navigation, and gates on objects that have no location of their
        own. Gates on a specific screen, group, or node ask user_grants instead.
        """
        rows = self.rows(
            """
            SELECT DISTINCT rp.permission
            FROM role_assignments a
            JOIN role_permissions rp ON rp.role_id = a.role_id
            WHERE a.user_id = ?
            """,
            (user_id,),
        )
        return permissions.normalise([row["permission"] for row in rows])

    def user_grants(self, user_id: int) -> tuple[tuple[str, str, int | None], ...]:
        """Every (permission, scope_type, scope_id) a user holds."""
        rows = self.rows(
            """
            SELECT DISTINCT rp.permission, a.scope_type, a.scope_id
            FROM role_assignments a
            JOIN role_permissions rp ON rp.role_id = a.role_id
            WHERE a.user_id = ?
            """,
            (user_id,),
        )
        return tuple(
            (str(row["permission"]), str(row["scope_type"] or "global"), row["scope_id"])
            for row in rows
            if permissions.is_known(str(row["permission"]))
        )

    def group_parents(self) -> dict[int, int | None]:
        """The whole group tree as a child -> parent map, in one query.

        Filtering a dashboard has to answer "is this screen inside a group I
        was granted" for every screen. Walking the tree per screen would be one
        recursive query each, so the shape is loaded once and walked in memory.
        """
        rows = self.rows("SELECT id, parent_id FROM tv_groups")
        return {int(row["id"]): (int(row["parent_id"]) if row["parent_id"] is not None else None) for row in rows}

    # --- roles ----------------------------------------------------------

    def list_roles(self) -> list[dict[str, Any]]:
        roles = self.rows(
            """
            SELECT r.id, r.name, r.description, r.builtin, r.created_at, r.updated_at,
                   (SELECT COUNT(*) FROM role_assignments a WHERE a.role_id = r.id) AS user_count
            FROM roles r
            ORDER BY r.builtin DESC, r.name
            """
        )
        for role in roles:
            role["permissions"] = sorted(self.role_permissions(int(role["id"])))
        return roles

    def get_role(self, role_id: int) -> dict[str, Any] | None:
        role = self.row("SELECT * FROM roles WHERE id = ?", (role_id,))
        if role:
            role["permissions"] = sorted(self.role_permissions(role_id))
        return role

    def get_role_by_name(self, name: str) -> dict[str, Any] | None:
        row = self.row("SELECT id FROM roles WHERE name = ?", (name,))
        return self.get_role(int(row["id"])) if row else None

    def role_permissions(self, role_id: int) -> frozenset[str]:
        rows = self.rows("SELECT permission FROM role_permissions WHERE role_id = ?", (role_id,))
        return permissions.normalise([row["permission"] for row in rows])

    def create_role(self, name: str, description: str, granted: frozenset[str]) -> int:
        now = int(time.time())
        role_id = self.execute(
            "INSERT INTO roles (name, description, builtin, created_at, updated_at) VALUES (?, ?, 0, ?, ?)",
            (name, description, now, now),
        )
        self.set_role_permissions(role_id, granted)
        return role_id

    def update_role(self, role_id: int, name: str, description: str, granted: frozenset[str]) -> None:
        self.execute(
            "UPDATE roles SET name = ?, description = ?, updated_at = ? WHERE id = ?",
            (name, description, int(time.time()), role_id),
        )
        self.set_role_permissions(role_id, granted)

    def set_role_permissions(self, role_id: int, granted: frozenset[str]) -> None:
        with self._lock, closing(self.connect()) as conn:
            conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
            conn.executemany(
                "INSERT INTO role_permissions (role_id, permission) VALUES (?, ?)",
                [(role_id, key) for key in sorted(permissions.normalise(granted))],
            )
            conn.commit()

    def delete_role(self, role_id: int) -> None:
        self.execute("DELETE FROM roles WHERE id = ?", (role_id,))

    def user_roles(self, user_id: int) -> list[dict[str, Any]]:
        return self.rows(
            """
            SELECT r.id, r.name, r.builtin, a.scope_type, a.scope_id,
                   g.name AS scope_group_name, n.name AS scope_node_name
            FROM role_assignments a
            JOIN roles r ON r.id = a.role_id
            LEFT JOIN tv_groups g ON a.scope_type = 'group' AND g.id = a.scope_id
            LEFT JOIN nodes n ON a.scope_type = 'node' AND n.id = a.scope_id
            WHERE a.user_id = ?
            ORDER BY r.builtin DESC, r.name, a.scope_type
            """,
            (user_id,),
        )

    def set_user_roles(self, user_id: int, assignments: list[dict[str, Any]]) -> None:
        """Replace a user's grants. Each entry is {role_id, scope_type, scope_id}."""
        now = int(time.time())
        rows = []
        for entry in assignments:
            scope_type = str(entry.get("scope_type") or "global")
            scope_id = entry.get("scope_id")
            rows.append((user_id, int(entry["role_id"]), scope_type, scope_id if scope_type != "global" else None, now))
        with self._lock, closing(self.connect()) as conn:
            conn.execute("DELETE FROM role_assignments WHERE user_id = ?", (user_id,))
            conn.executemany(
                """
                INSERT INTO role_assignments (user_id, role_id, scope_type, scope_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        # `users.role` is still reported by the API and shown in the panel, so
        # it has to follow the grants rather than drift away from them once
        # roles are assigned directly.
        self.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
            (permissions.derived_role(self.user_permissions(user_id)), int(time.time()), user_id),
        )

    def users_with_global_permission(self, permission: str) -> list[int]:
        """Enabled users holding a permission everywhere.

        Administering the installation cannot be delegated to somebody confined
        to one branch, so the last-administrator checks count global grants
        only.
        """
        rows = self.rows(
            """
            SELECT DISTINCT u.id
            FROM users u
            JOIN role_assignments a ON a.user_id = u.id
            JOIN role_permissions rp ON rp.role_id = a.role_id
            WHERE rp.permission = ? AND u.disabled = 0 AND a.scope_type = 'global'
            """,
            (permission,),
        )
        return [int(row["id"]) for row in rows]

    def users_with_permission_excluding_role(self, permission: str, role_id: int) -> list[int]:
        """Enabled users who would still hold a permission if one role lost it.

        Lets the API refuse an edit that would leave nobody able to administer
        the system, without having to apply it first and undo it.
        """
        rows = self.rows(
            """
            SELECT DISTINCT u.id
            FROM users u
            JOIN role_assignments a ON a.user_id = u.id
            JOIN role_permissions rp ON rp.role_id = a.role_id
            WHERE rp.permission = ? AND u.disabled = 0 AND a.role_id != ? AND a.scope_type = 'global'
            """,
            (permission, role_id),
        )
        return [int(row["id"]) for row in rows]

    def users_with_permission(self, permission: str) -> list[int]:
        """Ids of enabled users holding a permission. Used for last-admin checks."""
        rows = self.rows(
            """
            SELECT DISTINCT u.id
            FROM users u
            JOIN role_assignments a ON a.user_id = u.id
            JOIN role_permissions rp ON rp.role_id = a.role_id
            WHERE rp.permission = ? AND u.disabled = 0
            """,
            (permission,),
        )
        return [int(row["id"]) for row in rows]

    def list_sessions_for_user(self, user_id: int, current_token: str | None = None) -> list[dict[str, Any]]:
        current_hash = token_hash(current_token) if current_token else ""
        rows = self.rows(
            """
            SELECT id, token_hash, ip, user_agent, created_at, last_seen_at, expires_at
            FROM sessions
            WHERE user_id = ? AND expires_at >= ?
            ORDER BY last_seen_at DESC
            """,
            (user_id, int(time.time())),
        )
        return [
            {
                "id": row["id"],
                "ip": row.get("ip"),
                "user_agent": row.get("user_agent"),
                "created_at": row["created_at"],
                "last_seen_at": row["last_seen_at"],
                "expires_at": row["expires_at"],
                "current": row["token_hash"] == current_hash,
            }
            for row in rows
        ]

    def delete_other_sessions(self, user_id: int, current_token: str | None) -> int:
        sessions = self.list_sessions_for_user(user_id, current_token)
        removed = [session for session in sessions if not session["current"]]
        self.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
            (user_id, token_hash(current_token or "")),
        )
        return len(removed)

    def delete_session_by_id(self, user_id: int, session_id: int) -> bool:
        row = self.row("SELECT id FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
        if not row:
            return False
        self.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return True

    def delete_session(self, token: str | None) -> None:
        if token:
            self.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))

    def cleanup_sessions(self) -> None:
        self.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))

    def _seed_builtin_roles(self, conn: sqlite3.Connection) -> None:
        """Create the shipped roles and give every user the one they already had.

        Both families are seeded here: viewer/operator/admin, which `users.role`
        still names, and the branch presets, which only mean anything with a
        group attached and so are never written to that column.


        Runs inside init_schema's transaction on every start, and is idempotent:
        the permission set of a built-in role is rewritten to match the
        catalogue, so a release that adds a permission grants it to admins
        without a hand-written migration. Custom roles are never touched.

        Users are only backfilled if they hold no role at all. Somebody whose
        grants were deliberately changed must not have them reset on restart.
        """
        now = int(time.time())
        role_ids: dict[str, int] = {}
        for name in permissions.SEEDED_ROLES:
            conn.execute(
                """
                INSERT INTO roles (name, description, builtin, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(name) DO UPDATE SET description = excluded.description, builtin = 1, updated_at = ?
                """,
                (name, permissions.BUILTIN_ROLE_DESCRIPTIONS[name], now, now, now),
            )
            row = conn.execute("SELECT id FROM roles WHERE name = ?", (name,)).fetchone()
            role_ids[name] = int(row["id"])

            wanted = permissions.SEEDED_ROLES[name]
            conn.execute(
                f"DELETE FROM role_permissions WHERE role_id = ? AND permission NOT IN ({','.join('?' * len(wanted))})",
                (role_ids[name], *sorted(wanted)),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO role_permissions (role_id, permission) VALUES (?, ?)",
                [(role_ids[name], key) for key in sorted(wanted)],
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO role_assignments (user_id, role_id, created_at)
            SELECT u.id, r.id, ?
            FROM users u
            JOIN roles r ON r.name = u.role AND r.builtin = 1
            WHERE NOT EXISTS (SELECT 1 FROM role_assignments a WHERE a.user_id = u.id)
            """,
            (now,),
        )

    def _widen_role_assignment_key(self, conn: sqlite3.Connection) -> None:
        """One role, several branches: the old key allowed it only once.

        `UNIQUE(user_id, role_id)` predates scopes. It meant somebody curating
        two regions could not simply hold "media approver" on both -- the second
        grant collided with the first, and the way round it was to duplicate the
        role under another name. A column cannot be un-constrained in SQLite, so
        the table is rebuilt; nothing references it, which is what makes that
        safe here.

        Uniqueness moves into two partial indexes. A single UNIQUE over all four
        columns would not do: SQLite treats NULLs as distinct, so a global grant
        -- whose scope_id is NULL -- could be inserted twice over.
        """
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'role_assignments'").fetchone()
        if row and "UNIQUE(user_id, role_id)" in (row["sql"] or ""):
            conn.executescript(
                """
                CREATE TABLE role_assignments_wide (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    created_at INTEGER NOT NULL,
                    scope_type TEXT NOT NULL DEFAULT 'global',
                    scope_id INTEGER
                );
                INSERT INTO role_assignments_wide (id, user_id, role_id, created_at, scope_type, scope_id)
                    SELECT id, user_id, role_id, created_at, COALESCE(scope_type, 'global'), scope_id
                    FROM role_assignments;
                DROP TABLE role_assignments;
                ALTER TABLE role_assignments_wide RENAME TO role_assignments;
                """
            )
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS role_assignments_user ON role_assignments(user_id);
            CREATE UNIQUE INDEX IF NOT EXISTS role_assignments_scoped
                ON role_assignments(user_id, role_id, scope_type, scope_id) WHERE scope_id IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS role_assignments_global
                ON role_assignments(user_id, role_id) WHERE scope_id IS NULL;
            """
        )

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

    def fail_running_commands(self, error: str = "Interrupted by server restart") -> int:
        commands = self.rows("SELECT id, tv_id, command FROM tv_commands WHERE status = 'running'")
        if not commands:
            return 0
        now = int(time.time())
        self.execute(
            "UPDATE tv_commands SET status = 'failed', error = ?, finished_at = ? WHERE status = 'running'",
            (error, now),
        )
        for command in commands:
            self.add_event(command["tv_id"], "command_failed", f"{command['command']} failed", error)
        return len(commands)

    def recent_commands_for_tv(self, tv_id: int, limit: int = 5) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM tv_commands WHERE tv_id = ? ORDER BY id DESC LIMIT ?",
            (tv_id, limit),
        )

    EVENT_RETENTION = 1000
    SECURITY_EVENT_RETENTION = 5000
    TELEMETRY_EVENT_RETENTION = 500
    # Login/user/security audit events outlive the regular service event stream.
    _SECURITY_EVENT_FILTER = (
        "(event_type LIKE 'login%' OR event_type LIKE 'security%'"
        " OR event_type LIKE 'user%' OR event_type = 'logout')"
    )
    # Playback telemetry is written on every clip on every screen -- roughly
    # 800 rows a day on a five-screen site. Sharing one budget with the rest
    # meant the records you actually reach for, "why is this screen dark",
    # were evicted within two days by push/preload chatter. It gets its own
    # allowance so it can only ever crowd out itself.
    TELEMETRY_EVENT_TYPES = (
        "preload_next_uri",
        "preload_next_failed",
        "stream_playback_sync",
        "push_media",
        "replay_detected",
        "stream_end_detected",
        "duration_elapsed",
        "command_started",
        "command_done",
        "push_timeout_ignored",
        "skipped_not_ready",
    )
    _TELEMETRY_FILTER = "event_type IN ({})".format(",".join(f"'{name}'" for name in TELEMETRY_EVENT_TYPES))

    def add_event(self, tv_id: int | None, event_type: str, message: str, details: str | None = None) -> int:
        event_id = self.execute(
            """
            INSERT INTO events (tv_id, event_type, message, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tv_id, event_type, message, details, int(time.time())),
        )
        for condition, keep in (
            (f"NOT {self._SECURITY_EVENT_FILTER} AND NOT {self._TELEMETRY_FILTER}", self.EVENT_RETENTION),
            (self._SECURITY_EVENT_FILTER, self.SECURITY_EVENT_RETENTION),
            (self._TELEMETRY_FILTER, self.TELEMETRY_EVENT_RETENTION),
        ):
            self.execute(
                f"""
                DELETE FROM events WHERE ({condition})
                AND id NOT IN (
                    SELECT id FROM events WHERE ({condition})
                    ORDER BY id DESC LIMIT {keep}
                )
                """
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

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        return self.row("SELECT * FROM events WHERE id = ?", (event_id,))

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
        silent: bool = False,
        compressed: bool = False,
    ) -> int:
        now = int(time.time())
        return self.execute(
            """
            INSERT INTO media (title, original_path, original_name, size, checksum, duration_seconds,
                               silent, compressed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                str(original_path),
                original_name,
                size,
                checksum,
                duration_seconds,
                int(silent),
                int(compressed),
                now,
                now,
            ),
        )

    def update_media(self, media_id: int, title: str, description: str | None) -> None:
        self.execute(
            "UPDATE media SET title = ?, description = ?, updated_at = ? WHERE id = ?",
            (title, description or None, int(time.time()), media_id),
        )

    def media_usage(self, media_id: int) -> dict[str, Any]:
        """Where a clip is used right now: playlists holding it, screens playing it.

        Deleting or moving a clip without this is guesswork -- the delete used to
        cascade the item out of every playlist silently.
        """
        playlists = self.rows(
            """
            SELECT DISTINCT p.id, p.name, p.group_id
            FROM playlist_items i
            JOIN playlists p ON p.id = i.playlist_id
            WHERE i.media_id = ?
            ORDER BY p.name
            """,
            (media_id,),
        )
        tvs = self.rows(
            "SELECT id, name, group_id, node_id FROM tvs WHERE current_media_id = ? ORDER BY name",
            (media_id,),
        )
        return {"playlists": playlists, "tvs": tvs}

    def media_is_referenced(self, media_id: int) -> bool:
        """Whether any playlist still holds this clip.

        Asked before a purge, unfiltered by scope on purpose: a clip standing
        in a playlist the caller cannot see is still a clip that would vanish
        from under a running screen.
        """
        return self.row("SELECT 1 FROM playlist_items WHERE media_id = ? LIMIT 1", (media_id,)) is not None

    def set_media_lifecycle(self, media_id: int, state: str) -> None:
        if state not in lifecycle.STATES:
            raise ValueError(f"Unknown lifecycle state: {state}")
        self.execute(
            "UPDATE media SET lifecycle = ?, updated_at = ? WHERE id = ?",
            (state, int(time.time()), media_id),
        )

    def set_media_expiry(self, media_id: int, expires_at: int | None) -> None:
        self.execute(
            "UPDATE media SET expires_at = ?, updated_at = ? WHERE id = ?",
            (int(expires_at) if expires_at else None, int(time.time()), media_id),
        )

    def set_media_start(self, media_id: int, starts_at: int | None) -> None:
        self.execute(
            "UPDATE media SET starts_at = ?, updated_at = ? WHERE id = ?",
            (int(starts_at) if starts_at else None, int(time.time()), media_id),
        )

    def set_media_group(self, media_id: int, group_id: int | None) -> None:
        self.execute(
            "UPDATE media SET group_id = ?, updated_at = ? WHERE id = ?",
            (group_id, int(time.time()), media_id),
        )

    def set_playlist_group(self, playlist_id: int, group_id: int | None) -> None:
        self.execute("UPDATE playlists SET group_id = ? WHERE id = ?", (group_id, playlist_id))

    def list_media(self) -> list[dict[str, Any]]:
        # has_poster rather than the path: the panel only needs to know whether
        # to ask for the picture, and where the file sits on the server is none
        # of a branch operator's business.
        return self.rows(
            """
            SELECT *, (poster_path IS NOT NULL AND poster_path != '') AS has_poster
            FROM media
            ORDER BY created_at DESC
            """
        )

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

    def next_media_missing_poster(self) -> dict[str, Any] | None:
        """Oldest clip with no still taken yet, failures included as done.

        Duration has to be known first: the still is pulled a tenth of the way
        in, and a clip picked up before the probe ran would be stilled at second
        zero -- usually black -- and never looked at again.
        """
        return self.row(
            """
            SELECT * FROM media
            WHERE poster_path IS NULL AND duration_seconds IS NOT NULL
            ORDER BY created_at ASC
            LIMIT 1
            """
        )

    def set_media_poster(self, media_id: int, poster_path: str | None) -> None:
        """Empty records a failed attempt; None puts the clip back in the queue."""
        self.execute(
            "UPDATE media SET poster_path = ?, updated_at = ? WHERE id = ?",
            (poster_path, int(time.time()), media_id),
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

    def set_media_silent(self, media_id: int, silent: bool) -> None:
        self.execute(
            "UPDATE media SET silent = ?, updated_at = ? WHERE id = ?",
            (int(bool(silent)), int(time.time()), media_id),
        )

    def set_media_compressed(self, media_id: int, compressed: bool) -> None:
        self.execute(
            "UPDATE media SET compressed = ?, updated_at = ? WHERE id = ?",
            (int(bool(compressed)), int(time.time()), media_id),
        )

    def requeue_transcode_jobs_for_media(self, media_id: int) -> None:
        now = int(time.time())
        with self._lock, closing(self.connect()) as conn:
            conn.execute(
                """
                UPDATE transcode_jobs
                SET status = 'pending', attempts = 0, output_path = NULL, error = NULL, updated_at = ?
                WHERE media_id = ?
                """,
                (now, media_id),
            )
            conn.execute(
                "UPDATE media SET status = 'uploaded', error = NULL, transcoded_path = NULL, updated_at = ? WHERE id = ?",
                (now, media_id),
            )
            conn.commit()

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

    def set_playlist_item_position(self, item_id: int, position: int) -> None:
        item = self.row("SELECT * FROM playlist_items WHERE id = ?", (item_id,))
        if not item:
            return
        rows = self.rows(
            "SELECT id FROM playlist_items WHERE playlist_id = ? ORDER BY position, id",
            (item["playlist_id"],),
        )
        ordered_ids = [row["id"] for row in rows if row["id"] != item_id]
        position = max(0, min(position, len(ordered_ids)))
        ordered_ids.insert(position, item_id)
        with self._lock, closing(self.connect()) as conn:
            # Two passes keep UNIQUE(playlist_id, position) satisfied mid-update.
            for index, row_id in enumerate(ordered_ids):
                conn.execute("UPDATE playlist_items SET position = ? WHERE id = ?", (-(index + 1), row_id))
            for index, row_id in enumerate(ordered_ids):
                conn.execute("UPDATE playlist_items SET position = ? WHERE id = ?", (index, row_id))
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

    # ----- TV groups (tree) -----

    MAX_GROUP_DEPTH = 8

    def list_groups(self) -> list[dict[str, Any]]:
        """Every group with its depth and materialised path, ordered for display."""
        return self.rows(
            """
            WITH RECURSIVE tree(id, name, parent_id, depth, path, sort_key) AS (
                SELECT id, name, parent_id, 0, name, name
                FROM tv_groups WHERE parent_id IS NULL
                UNION ALL
                SELECT g.id, g.name, g.parent_id, tree.depth + 1,
                       tree.path || ' / ' || g.name, tree.sort_key || char(31) || g.name
                FROM tv_groups g JOIN tree ON g.parent_id = tree.id
            )
            SELECT tree.id, tree.name, tree.parent_id, tree.depth, tree.path,
                   group_data.schedule_mode, group_data.schedule_days,
                   group_data.schedule_start, group_data.schedule_end,
                   (SELECT COUNT(*) FROM tvs t WHERE t.group_id = tree.id) AS tv_count
            FROM tree
            JOIN tv_groups group_data ON group_data.id = tree.id
            ORDER BY tree.sort_key
            """
        )

    def _with_group_schedule_chains(self, tvs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Attach each TV's groups nearest-first with one group query per batch."""
        groups = {
            int(group["id"]): group
            for group in self.rows(
                """
                SELECT id, parent_id, schedule_mode, schedule_days,
                       schedule_start, schedule_end
                FROM tv_groups
                """
            )
        }
        for tv in tvs:
            chain = []
            group_id = tv.get("group_id")
            visited: set[int] = set()
            while group_id is not None and int(group_id) not in visited:
                current_id = int(group_id)
                visited.add(current_id)
                group = groups.get(current_id)
                if group is None:
                    break
                chain.append(dict(group))
                group_id = group.get("parent_id")
            tv["schedule_groups"] = chain
        return tvs

    def _with_group_schedule_chain(self, tv: dict[str, Any]) -> dict[str, Any]:
        """Attach one TV's bounded ancestry without loading unrelated groups."""
        group_id = tv.get("group_id")
        if group_id is None:
            tv["schedule_groups"] = []
            return tv
        tv["schedule_groups"] = self.rows(
            """
            WITH RECURSIVE ancestors(
                id, parent_id, schedule_mode, schedule_days,
                schedule_start, schedule_end, depth
            ) AS (
                SELECT id, parent_id, schedule_mode, schedule_days,
                       schedule_start, schedule_end, 0
                FROM tv_groups WHERE id = ?
                UNION ALL
                SELECT g.id, g.parent_id, g.schedule_mode, g.schedule_days,
                       g.schedule_start, g.schedule_end, ancestors.depth + 1
                FROM tv_groups g JOIN ancestors ON g.id = ancestors.parent_id
                WHERE ancestors.depth + 1 < ?
            )
            SELECT id, parent_id, schedule_mode, schedule_days,
                   schedule_start, schedule_end
            FROM ancestors ORDER BY depth
            """,
            (int(group_id), self.MAX_GROUP_DEPTH),
        )
        return tv

    def group_subtree_ids(self, group_id: int) -> list[int]:
        """The group itself plus every descendant."""
        rows = self.rows(
            """
            WITH RECURSIVE subtree(id) AS (
                SELECT id FROM tv_groups WHERE id = ?
                UNION
                SELECT g.id FROM tv_groups g JOIN subtree ON g.parent_id = subtree.id
            )
            SELECT id FROM subtree
            """,
            (group_id,),
        )
        return [int(row["id"]) for row in rows]

    def group_ancestors(self, group_id: int) -> list[int]:
        """The group itself plus every ancestor, nearest first."""
        rows = self.rows(
            """
            WITH RECURSIVE chain(id, parent_id, depth) AS (
                SELECT id, parent_id, 0 FROM tv_groups WHERE id = ?
                UNION ALL
                SELECT g.id, g.parent_id, chain.depth + 1
                FROM tv_groups g JOIN chain ON g.id = chain.parent_id
            )
            SELECT id FROM chain ORDER BY depth
            """,
            (group_id,),
        )
        return [int(row["id"]) for row in rows]

    def get_group(self, group_id: int) -> dict[str, Any] | None:
        return self.row("SELECT * FROM tv_groups WHERE id = ?", (group_id,))

    def group_depth(self, group_id: int | None) -> int:
        return 0 if group_id is None else len(self.group_ancestors(group_id))

    def group_height(self, group_id: int) -> int:
        row = self.row(
            """
            WITH RECURSIVE subtree(id, depth) AS (
                SELECT id, 1 FROM tv_groups WHERE id = ?
                UNION ALL
                SELECT g.id, subtree.depth + 1
                FROM tv_groups g JOIN subtree ON g.parent_id = subtree.id
            )
            SELECT COALESCE(MAX(depth), 0) AS height FROM subtree
            """,
            (group_id,),
        )
        return int(row["height"] if row else 0)

    def create_group(
        self,
        name: str,
        parent_id: int | None = None,
        schedule_values: GroupScheduleValues = ("inherit", None, None, None),
    ) -> int:
        mode, days, start, end = schedule_values
        now = int(time.time())
        return self.execute(
            """
            INSERT INTO tv_groups (
                name, parent_id, schedule_mode, schedule_days,
                schedule_start, schedule_end, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name.strip(), parent_id, mode, days, start, end, now, now),
        )

    def rename_group(self, group_id: int, name: str) -> None:
        self.execute(
            "UPDATE tv_groups SET name = ?, updated_at = ? WHERE id = ?",
            (name.strip(), int(time.time()), group_id),
        )

    def move_group(self, group_id: int, parent_id: int | None) -> None:
        self.execute(
            "UPDATE tv_groups SET parent_id = ?, updated_at = ? WHERE id = ?",
            (parent_id, int(time.time()), group_id),
        )

    def update_group(
        self,
        group_id: int,
        name: str | None,
        parent_id: int | None,
        move: bool,
        schedule_values: GroupScheduleValues | None = None,
    ) -> None:
        if name is None and not move and schedule_values is None:
            return
        updates = ["updated_at = ?"]
        params: list[Any] = [int(time.time())]
        if name is not None:
            updates.append("name = ?")
            params.append(name.strip())
        if move:
            updates.append("parent_id = ?")
            params.append(parent_id)
        if schedule_values is not None:
            mode, days, start, end = schedule_values
            updates.extend(
                [
                    "schedule_mode = ?",
                    "schedule_days = ?",
                    "schedule_start = ?",
                    "schedule_end = ?",
                ]
            )
            params.extend([mode, days, start, end])
        params.append(group_id)
        self.execute(f"UPDATE tv_groups SET {', '.join(updates)} WHERE id = ?", tuple(params))

    def delete_group(self, group_id: int) -> None:
        # ON DELETE CASCADE removes descendants; TVs fall back to "no group"
        # rather than disappearing with it.
        for descendant in self.group_subtree_ids(group_id):
            self.execute("UPDATE tvs SET group_id = NULL WHERE group_id = ?", (descendant,))
        self.execute("DELETE FROM tv_groups WHERE id = ?", (group_id,))

    def distinct_tv_profiles(self) -> list[str]:
        rows = self.rows("SELECT DISTINCT profile FROM tvs WHERE profile IS NOT NULL AND profile <> ''")
        return [str(row["profile"]) for row in rows]

    def list_tvs(self) -> list[dict[str, Any]]:
        return self._with_group_schedule_chains(self.rows(
            """
            SELECT
                t.*,
                node.name AS node_name,
                grp.name AS group_name,
                p.name AS playlist_name,
                current_media.duration_seconds AS current_media_duration_seconds,
                current_media.title AS current_media_title,
                next_media.id AS next_media_id,
                next_media.title AS next_media_title,
                last_command.command AS last_command,
                last_command.status AS last_command_status,
                last_command.error AS last_command_error,
                last_command.created_at AS last_command_created_at,
                last_command.started_at AS last_command_started_at,
                last_command.finished_at AS last_command_finished_at,
                last_event.event_type AS last_event_type,
                last_event.message AS last_event_message,
                last_event.details AS last_event_details,
                last_event.created_at AS last_event_created_at,
                last_stream_event.event_type AS last_stream_event_type,
                last_stream_event.message AS last_stream_event_message,
                last_stream_event.details AS last_stream_event_details,
                last_stream_event.created_at AS last_stream_event_created_at,
                (
                    SELECT COUNT(*)
                    FROM tv_commands pending_command
                    WHERE pending_command.tv_id = t.id
                      AND pending_command.status IN ('pending', 'running')
                ) AS active_command_count
            FROM tvs t
            LEFT JOIN nodes node ON node.id = t.node_id
            LEFT JOIN tv_groups grp ON grp.id = t.group_id
            LEFT JOIN playlists p ON p.id = t.active_playlist_id
            LEFT JOIN media current_media ON current_media.id = t.current_media_id
            LEFT JOIN playlist_items next_item
                ON next_item.playlist_id = t.active_playlist_id
                AND next_item.position = t.current_index
            LEFT JOIN media next_media ON next_media.id = next_item.media_id
            LEFT JOIN tv_commands last_command
                ON last_command.id = (
                    SELECT c.id FROM tv_commands c
                    WHERE c.tv_id = t.id
                    ORDER BY c.id DESC
                    LIMIT 1
                )
            LEFT JOIN events last_event
                ON last_event.id = (
                    SELECT e.id FROM events e
                    WHERE e.tv_id = t.id
                    ORDER BY e.id DESC
                    LIMIT 1
                )
            LEFT JOIN events last_stream_event
                ON last_stream_event.id = (
                    SELECT se.id FROM events se
                    WHERE se.tv_id = t.id
                      AND se.event_type IN (
                          'push_media', 'preload_next_uri', 'stream_playback_sync', 'push_timeout_ignored',
                          'stream_end_detected', 'replay_detected', 'duration_elapsed', 'skipped_not_ready',
                          'preload_next_failed'
                      )
                    ORDER BY se.id DESC
                    LIMIT 1
                )
            ORDER BY t.name
            """
        ))

    # --- settings -------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.row("SELECT value FROM settings WHERE key = ?", (key,))
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, int(time.time())),
        )

    SCHEDULE_DEFAULTS = {
        # Off by default: an upgrade must never start blanking screens that
        # nobody asked to be blanked.
        "schedule.enabled": "false",
        "schedule.days": "0,1,2,3,4",
        "schedule.start": "08:00",
        "schedule.end": "20:00",
    }

    def get_playback_schedule(self) -> dict[str, Any]:
        return {
            "enabled": self.get_setting("schedule.enabled", self.SCHEDULE_DEFAULTS["schedule.enabled"]) == "true",
            "days": self.get_setting("schedule.days", self.SCHEDULE_DEFAULTS["schedule.days"]),
            "start": self.get_setting("schedule.start", self.SCHEDULE_DEFAULTS["schedule.start"]),
            "end": self.get_setting("schedule.end", self.SCHEDULE_DEFAULTS["schedule.end"]),
        }

    MEDIA_DEFAULTS = {"media.default_silent": "false", "media.default_compressed": "false"}

    def get_media_defaults(self) -> dict[str, bool]:
        """How a freshly uploaded clip should be transcoded.

        Both default to false, so an upgrade keeps producing exactly what it
        produced before.
        """
        return {
            "silent": self.get_setting("media.default_silent", self.MEDIA_DEFAULTS["media.default_silent"]) == "true",
            "compressed": self.get_setting("media.default_compressed", self.MEDIA_DEFAULTS["media.default_compressed"])
            == "true",
        }

    def set_media_defaults(self, silent: bool, compressed: bool) -> None:
        self.set_setting("media.default_silent", "true" if silent else "false")
        self.set_setting("media.default_compressed", "true" if compressed else "false")

    def set_playback_schedule(self, enabled: bool, days: str, start: str, end: str) -> None:
        self.set_setting("schedule.enabled", "true" if enabled else "false")
        self.set_setting("schedule.days", days)
        self.set_setting("schedule.start", start)
        self.set_setting("schedule.end", end)

    # --- playback suspension --------------------------------------------

    def suspend_tv_playback(self, tv_id: int, reason: str) -> None:
        """Record that a screen must be left alone until someone resumes it."""
        now = int(time.time())
        self.execute(
            """
            UPDATE tvs
            SET playback_suspended_at = ?, playback_suspended_reason = ?, updated_at = ?
            WHERE id = ? AND playback_suspended_at IS NULL
            """,
            (now, reason, now, tv_id),
        )

    def resume_tv_playback(self, tv_id: int) -> bool:
        """Clear a suspension. Returns True when there was one to clear."""
        tv = self.get_tv(tv_id)
        if not tv or tv.get("playback_suspended_at") is None:
            return False
        self.execute(
            """
            UPDATE tvs
            SET playback_suspended_at = NULL, playback_suspended_reason = NULL, updated_at = ?
            WHERE id = ?
            """,
            (int(time.time()), tv_id),
        )
        return True

    def update_tv_schedule(
        self,
        tv_id: int,
        mode: str,
        days: str | None,
        start: str | None,
        end: str | None,
    ) -> None:
        self.execute(
            """
            UPDATE tvs
            SET schedule_mode = ?, schedule_days = ?, schedule_start = ?, schedule_end = ?, updated_at = ?
            WHERE id = ?
            """,
            (mode, days, start, end, int(time.time()), tv_id),
        )

    def get_tv(self, tv_id: int) -> dict[str, Any] | None:
        tv = self.row("SELECT * FROM tvs WHERE id = ?", (tv_id,))
        return self._with_group_schedule_chain(tv) if tv else None

    def get_tv_by_ip(self, ip: str) -> dict[str, Any] | None:
        tv = self.row("SELECT * FROM tvs WHERE ip = ?", (ip,))
        return self._with_group_schedule_chain(tv) if tv else None

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
            SET control_url = NULL, rendering_control_url = NULL,
                online = 0, dlna_reachable = 0, soap_ready = 0, streaming = 0,
                playback_state = 'OFFLINE',
                last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (error, int(time.time()), tv_id),
        )

    def mark_tv_unreachable(self, tv_id: int) -> None:
        self.execute(
            """
            UPDATE tvs
            SET online = 0, ping_reachable = 0, dlna_reachable = 0,
                soap_ready = 0, streaming = 0, playback_state = 'OFFLINE',
                updated_at = ?
            WHERE id = ?
            """,
            (int(time.time()), tv_id),
        )

    def update_tv_discovery(self, tv_id: int, info: dict[str, Any], profile: str) -> None:
        now = int(time.time())
        self.execute(
            """
            UPDATE tvs
            SET manufacturer = ?, model_name = ?, friendly_name = ?, control_url = ?,
                rendering_control_url = ?, profile = ?, last_error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (
                info.get("manufacturer"),
                info.get("model_name"),
                info.get("friendly_name"),
                info.get("control_url"),
                info.get("rendering_control_url"),
                profile,
                now,
                tv_id,
            ),
        )

    def set_tv_rendering_control_url(self, tv_id: int, url: str | None) -> None:
        self.execute(
            "UPDATE tvs SET rendering_control_url = ?, updated_at = ? WHERE id = ?",
            (url or None, int(time.time()), tv_id),
        )

    def set_tv_muted(self, tv_id: int, muted: bool) -> None:
        self.execute(
            "UPDATE tvs SET muted = ?, updated_at = ? WHERE id = ?",
            (int(bool(muted)), int(time.time()), tv_id),
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

    def mark_tv_stream_playback(self, tv_id: int, index: int, media_id: int, reset_started: bool) -> None:
        now = int(time.time())
        self.execute(
            """
            UPDATE tvs
            SET current_index = ?, current_media_id = ?,
                online = 1, ping_reachable = 1, dlna_reachable = 1, soap_ready = 1,
                streaming = 1, playback_state = 'PLAYING',
                playback_started_at = CASE
                    WHEN ? THEN ?
                    ELSE COALESCE(playback_started_at, ?)
                END,
                last_replay_advance_at = CASE WHEN ? THEN NULL ELSE last_replay_advance_at END,
                last_seen = ?, last_error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (
                index,
                media_id,
                int(reset_started),
                now,
                now,
                int(reset_started),
                now,
                now,
                tv_id,
            ),
        )

    def mark_tv_replay_advance(self, tv_id: int) -> None:
        self.execute(
            "UPDATE tvs SET last_replay_advance_at = ?, updated_at = ? WHERE id = ?",
            (int(time.time()), int(time.time()), tv_id),
        )

    def set_tv_control_url(self, tv_id: int, control_url: str) -> None:
        self.execute("UPDATE tvs SET control_url = ?, updated_at = ? WHERE id = ?", (control_url, int(time.time()), tv_id))

    def export_tvs(self) -> list[dict[str, Any]]:
        rows = self.rows(
            """
            SELECT name, ip, manufacturer, model_name, friendly_name, profile, control_url,
                   rendering_control_url, autoplay, muted, repeat_mode
            FROM tvs
            ORDER BY name
            """
        )
        return [
            {
                "name": row["name"],
                "ip": row["ip"],
                "manufacturer": row.get("manufacturer"),
                "model_name": row.get("model_name"),
                "friendly_name": row.get("friendly_name"),
                "profile": row["profile"],
                "control_url": row.get("control_url"),
                "rendering_control_url": row.get("rendering_control_url"),
                "autoplay": bool(row.get("autoplay")),
                "muted": bool(row.get("muted")),
                "repeat_mode": row.get("repeat_mode") or "all",
            }
            for row in rows
        ]

    def import_tvs(self, tvs: list[dict[str, Any]]) -> tuple[int, int]:
        created = 0
        updated = 0
        for item in tvs:
            ip = str(item.get("ip") or "").strip()
            if not ip:
                continue
            name = str(item.get("name") or ip).strip()
            profile = str(item.get("profile") or "generic_dlna").strip()
            control_url = str(item.get("control_url") or "").strip()
            autoplay = bool(item.get("autoplay", True))
            existing = self.get_tv_by_ip(ip)
            if existing:
                self.update_tv_config(
                    existing["id"],
                    name,
                    ip,
                    profile,
                    existing.get("active_playlist_id"),
                    autoplay,
                    control_url,
                )
                tv_id = existing["id"]
                updated += 1
            else:
                tv_id = self.add_tv(name, ip, profile)
                if control_url:
                    self.set_tv_control_url(tv_id, control_url)
                created += 1
            rendering_control_url = str(item.get("rendering_control_url") or "").strip() or None
            self.execute(
                """
                UPDATE tvs
                SET manufacturer = ?, model_name = ?, friendly_name = ?,
                    rendering_control_url = ?, muted = ?,
                    repeat_mode = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    item.get("manufacturer"),
                    item.get("model_name"),
                    item.get("friendly_name"),
                    rendering_control_url,
                    int(bool(item.get("muted"))),
                    str(item.get("repeat_mode") or "all"),
                    int(time.time()),
                    tv_id,
                ),
            )
        return created, updated
