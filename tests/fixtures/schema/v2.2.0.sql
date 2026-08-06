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
                );
INSERT INTO "media" VALUES(1,'media-title-1','media-original_path-1','media-original_name-1',1,'media-checksum-1','uploaded',NULL,NULL,0,0,NULL,1,1);
INSERT INTO "media" VALUES(2,'media-title-2','media-original_path-2','media-original_name-2',2,'media-checksum-2','uploaded',NULL,NULL,0,0,NULL,2,2);
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
                );
INSERT INTO "playlists" VALUES(1,'playlists-name-1',1);
INSERT INTO "playlists" VALUES(2,'playlists-name-2',2);
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
                , node_id INTEGER REFERENCES nodes(id) ON DELETE SET NULL);
INSERT INTO "tvs" VALUES(1,'tvs-name-1','tvs-ip-1',NULL,NULL,NULL,'generic_dlna',NULL,NULL,NULL,0,NULL,1,0,'all',0,0,0,0,0,'UNKNOWN',NULL,NULL,NULL,NULL,1,1,NULL);
INSERT INTO "tvs" VALUES(2,'tvs-name-2','tvs-ip-2',NULL,NULL,NULL,'generic_dlna',NULL,NULL,NULL,0,NULL,1,0,'all',0,0,0,0,0,'UNKNOWN',NULL,NULL,NULL,NULL,2,2,NULL);
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
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('events',2);
INSERT INTO "sqlite_sequence" VALUES('media',2);
INSERT INTO "sqlite_sequence" VALUES('nodes',2);
INSERT INTO "sqlite_sequence" VALUES('playlist_items',2);
INSERT INTO "sqlite_sequence" VALUES('playlists',2);
INSERT INTO "sqlite_sequence" VALUES('sessions',2);
INSERT INTO "sqlite_sequence" VALUES('transcode_jobs',2);
INSERT INTO "sqlite_sequence" VALUES('tv_commands',2);
INSERT INTO "sqlite_sequence" VALUES('tvs',2);
INSERT INTO "sqlite_sequence" VALUES('users',2);
COMMIT;
