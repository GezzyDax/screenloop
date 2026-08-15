BEGIN TRANSACTION;
CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tv_id INTEGER REFERENCES tvs(id) ON DELETE SET NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT,
                    created_at INTEGER NOT NULL
                );
INSERT INTO "events" VALUES(1,NULL,'events-event_type-1','events-message-1',NULL,1);
INSERT INTO "events" VALUES(2,NULL,'events-event_type-2','events-message-2',NULL,2);
CREATE TABLE media (
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
                , group_id INTEGER REFERENCES tv_groups(id) ON DELETE SET NULL);
INSERT INTO "media" VALUES(1,'media-title-1','media-original_path-1','media-original_name-1',1,'media-checksum-1','uploaded',NULL,NULL,0,0,NULL,1,1,NULL);
INSERT INTO "media" VALUES(2,'media-title-2','media-original_path-2','media-original_name-2',2,'media-checksum-2','uploaded',NULL,NULL,0,0,NULL,2,2,NULL);
CREATE TABLE nodes (
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
INSERT INTO "nodes" VALUES(1,'nodes-name-1',NULL,NULL,NULL,NULL,NULL,0,NULL,0,1,1);
INSERT INTO "nodes" VALUES(2,'nodes-name-2',NULL,NULL,NULL,NULL,NULL,0,NULL,0,2,2);
CREATE TABLE playlist_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    UNIQUE(playlist_id, position)
                );
INSERT INTO "playlist_items" VALUES(1,1,1,1);
INSERT INTO "playlist_items" VALUES(2,1,1,2);
CREATE TABLE playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at INTEGER NOT NULL
                , group_id INTEGER REFERENCES tv_groups(id) ON DELETE SET NULL);
INSERT INTO "playlists" VALUES(1,'playlists-name-1',1,NULL);
INSERT INTO "playlists" VALUES(2,'playlists-name-2',2,NULL);
CREATE TABLE role_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    created_at INTEGER NOT NULL, scope_type TEXT NOT NULL DEFAULT 'global', scope_id INTEGER,
                    UNIQUE(user_id, role_id)
                );
-- Added by hand: the generic seeding in scripts/schema_fixture.py cannot
-- satisfy UNIQUE(user_id, role_id) and leaves this table empty, which would
-- make the fixture an installation nobody has any access to. A real one has
-- both a global grant and a scoped one, and both have to survive the upgrade.
INSERT INTO "role_assignments" VALUES(1,1,3,1786826334,'global',NULL);
INSERT INTO "role_assignments" VALUES(2,2,1,1786826334,'group',1);
CREATE TABLE role_permissions (
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    permission TEXT NOT NULL,
                    PRIMARY KEY (role_id, permission)
                );
INSERT INTO "role_permissions" VALUES(1,'event.view');
INSERT INTO "role_permissions" VALUES(1,'group.view');
INSERT INTO "role_permissions" VALUES(1,'media.view');
INSERT INTO "role_permissions" VALUES(1,'playlist.view');
INSERT INTO "role_permissions" VALUES(1,'schedule.view');
INSERT INTO "role_permissions" VALUES(1,'transcode.view');
INSERT INTO "role_permissions" VALUES(1,'tv.view');
INSERT INTO "role_permissions" VALUES(2,'event.security.view');
INSERT INTO "role_permissions" VALUES(2,'event.view');
INSERT INTO "role_permissions" VALUES(2,'group.view');
INSERT INTO "role_permissions" VALUES(2,'media.defaults.manage');
INSERT INTO "role_permissions" VALUES(2,'media.manage');
INSERT INTO "role_permissions" VALUES(2,'media.upload');
INSERT INTO "role_permissions" VALUES(2,'media.view');
INSERT INTO "role_permissions" VALUES(2,'playlist.edit');
INSERT INTO "role_permissions" VALUES(2,'playlist.view');
INSERT INTO "role_permissions" VALUES(2,'schedule.view');
INSERT INTO "role_permissions" VALUES(2,'transcode.rebuild');
INSERT INTO "role_permissions" VALUES(2,'transcode.view');
INSERT INTO "role_permissions" VALUES(2,'tv.command');
INSERT INTO "role_permissions" VALUES(2,'tv.view');
INSERT INTO "role_permissions" VALUES(3,'diagnostics.view');
INSERT INTO "role_permissions" VALUES(3,'event.security.view');
INSERT INTO "role_permissions" VALUES(3,'event.view');
INSERT INTO "role_permissions" VALUES(3,'group.manage');
INSERT INTO "role_permissions" VALUES(3,'group.view');
INSERT INTO "role_permissions" VALUES(3,'media.defaults.manage');
INSERT INTO "role_permissions" VALUES(3,'media.delete');
INSERT INTO "role_permissions" VALUES(3,'media.manage');
INSERT INTO "role_permissions" VALUES(3,'media.share');
INSERT INTO "role_permissions" VALUES(3,'media.upload');
INSERT INTO "role_permissions" VALUES(3,'media.view');
INSERT INTO "role_permissions" VALUES(3,'node.enrol');
INSERT INTO "role_permissions" VALUES(3,'node.manage');
INSERT INTO "role_permissions" VALUES(3,'node.view');
INSERT INTO "role_permissions" VALUES(3,'playlist.assign');
INSERT INTO "role_permissions" VALUES(3,'playlist.delete');
INSERT INTO "role_permissions" VALUES(3,'playlist.edit');
INSERT INTO "role_permissions" VALUES(3,'playlist.share');
INSERT INTO "role_permissions" VALUES(3,'playlist.view');
INSERT INTO "role_permissions" VALUES(3,'role.manage');
INSERT INTO "role_permissions" VALUES(3,'schedule.manage');
INSERT INTO "role_permissions" VALUES(3,'schedule.site.manage');
INSERT INTO "role_permissions" VALUES(3,'schedule.view');
INSERT INTO "role_permissions" VALUES(3,'template.manage');
INSERT INTO "role_permissions" VALUES(3,'template.view');
INSERT INTO "role_permissions" VALUES(3,'transcode.manage');
INSERT INTO "role_permissions" VALUES(3,'transcode.rebuild');
INSERT INTO "role_permissions" VALUES(3,'transcode.view');
INSERT INTO "role_permissions" VALUES(3,'tv.command');
INSERT INTO "role_permissions" VALUES(3,'tv.manage');
INSERT INTO "role_permissions" VALUES(3,'tv.scan');
INSERT INTO "role_permissions" VALUES(3,'tv.transfer');
INSERT INTO "role_permissions" VALUES(3,'tv.view');
INSERT INTO "role_permissions" VALUES(3,'user.manage');
CREATE TABLE roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    builtin INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
INSERT INTO "roles" VALUES(1,'viewer','Read-only access to screens, media, playlists, and playback events.',1,1786826334,1786826334);
INSERT INTO "roles" VALUES(2,'operator','Everything a viewer can do, plus playback control, uploads, and playlist edits.',1,1786826334,1786826334);
INSERT INTO "roles" VALUES(3,'admin','Full access, including users, roles, devices, and templates.',1,1786826334,1786826334);
INSERT INTO "roles" VALUES(4,'roles-name-1',NULL,0,1,1);
INSERT INTO "roles" VALUES(5,'roles-name-2',NULL,0,2,2);
CREATE TABLE sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    ip TEXT,
                    user_agent TEXT,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL
                );
INSERT INTO "sessions" VALUES(1,1,'sessions-token_hash-1',NULL,NULL,1,1,1);
INSERT INTO "sessions" VALUES(2,1,'sessions-token_hash-2',NULL,NULL,2,2,2);
CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
INSERT INTO "settings" VALUES(NULL,'settings-value-1',1);
INSERT INTO "settings" VALUES(NULL,'settings-value-2',2);
CREATE TABLE transcode_jobs (
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
INSERT INTO "transcode_jobs" VALUES(1,1,'transcode_jobs-profile-1','pending',0,NULL,NULL,1,1);
INSERT INTO "transcode_jobs" VALUES(2,1,'transcode_jobs-profile-2','pending',0,NULL,NULL,2,2);
CREATE TABLE tv_commands (
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
INSERT INTO "tv_commands" VALUES(1,1,'tv_commands-command-1','pending',NULL,NULL,1,NULL,NULL);
INSERT INTO "tv_commands" VALUES(2,1,'tv_commands-command-2','pending',NULL,NULL,2,NULL,NULL);
CREATE TABLE tv_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    parent_id INTEGER REFERENCES tv_groups(id) ON DELETE CASCADE,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                , schedule_mode TEXT NOT NULL DEFAULT 'inherit', schedule_days TEXT, schedule_start TEXT, schedule_end TEXT);
INSERT INTO "tv_groups" VALUES(1,'tv_groups-name-1',NULL,1,1,'inherit',NULL,NULL,NULL);
INSERT INTO "tv_groups" VALUES(2,'tv_groups-name-2',NULL,2,2,'inherit',NULL,NULL,NULL);
CREATE TABLE tvs (
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
                , node_id INTEGER REFERENCES nodes(id) ON DELETE SET NULL, group_id INTEGER REFERENCES tv_groups(id) ON DELETE SET NULL, schedule_mode TEXT NOT NULL DEFAULT 'inherit', schedule_days TEXT, schedule_start TEXT, schedule_end TEXT, playback_suspended_at INTEGER, playback_suspended_reason TEXT);
INSERT INTO "tvs" VALUES(1,'tvs-name-1','tvs-ip-1',NULL,NULL,NULL,'generic_dlna',NULL,NULL,NULL,0,NULL,1,0,'all',0,0,0,0,0,'UNKNOWN',NULL,NULL,NULL,NULL,1,1,NULL,NULL,'inherit',NULL,NULL,NULL,NULL,NULL);
INSERT INTO "tvs" VALUES(2,'tvs-name-2','tvs-ip-2',NULL,NULL,NULL,'generic_dlna',NULL,NULL,NULL,0,NULL,1,0,'all',0,0,0,0,0,'UNKNOWN',NULL,NULL,NULL,NULL,2,2,NULL,NULL,'inherit',NULL,NULL,NULL,NULL,NULL);
CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
INSERT INTO "users" VALUES(1,'users-username-1','users-password_hash-1','users-role-1',0,1,1);
INSERT INTO "users" VALUES(2,'users-username-2','users-password_hash-2','users-role-2',0,2,2);
CREATE UNIQUE INDEX tv_groups_unique_child
                    ON tv_groups(parent_id, name) WHERE parent_id IS NOT NULL;
CREATE UNIQUE INDEX tv_groups_unique_root
                    ON tv_groups(name) WHERE parent_id IS NULL;
CREATE INDEX role_assignments_user ON role_assignments(user_id);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('roles',5);
INSERT INTO "sqlite_sequence" VALUES('role_assignments',0);
INSERT INTO "sqlite_sequence" VALUES('events',2);
INSERT INTO "sqlite_sequence" VALUES('media',2);
INSERT INTO "sqlite_sequence" VALUES('nodes',2);
INSERT INTO "sqlite_sequence" VALUES('playlist_items',2);
INSERT INTO "sqlite_sequence" VALUES('playlists',2);
INSERT INTO "sqlite_sequence" VALUES('sessions',2);
INSERT INTO "sqlite_sequence" VALUES('transcode_jobs',2);
INSERT INTO "sqlite_sequence" VALUES('tv_commands',2);
INSERT INTO "sqlite_sequence" VALUES('tv_groups',2);
INSERT INTO "sqlite_sequence" VALUES('tvs',2);
INSERT INTO "sqlite_sequence" VALUES('users',2);
COMMIT;
