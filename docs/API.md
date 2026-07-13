# Screenloop API

Screenloop exposes a JSON API under `/api/v1` for the Vue UI and trusted LAN integrations. The API is the only supported control surface; the legacy server-rendered panel has been removed.

## Authentication

Login creates an HttpOnly cookie session:

```bash
curl -i -X POST http://localhost:8099/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"your-password"}'
```

The response contains the current user and a `csrf_token`. Store the CSRF token in frontend state, not localStorage. The session itself is stored in the `screenloop_session` HttpOnly cookie.

Refresh session context:

```bash
curl -b cookies.txt http://localhost:8099/api/v1/session
```

Logout:

```bash
curl -X POST http://localhost:8099/api/v1/auth/logout \
  -b cookies.txt \
  -H "X-CSRF-Token: $CSRF"
```

## CSRF And Roles

All unsafe methods (`POST`, `PATCH`, `DELETE`) require:

```http
X-CSRF-Token: <token from login or /api/v1/session>
```

Roles:

- `viewer`: read-only status, media, playlists, TVs, events, transcode jobs. Security audit events (`login*`, `security*`, `user*`, `logout`) are hidden from viewers in `/api/v1/events` and the SSE snapshot.
- `operator`: viewer access plus playback commands, playlist edits, media upload, transcode rebuilds, and the full event log.
- `admin`: full access, including users, TV config, delete/import/export, cache cleanup.

The API returns `401` for missing/invalid sessions, `403` for missing CSRF or insufficient role, and `429` for rate-limited actions. Login attempts are rate-limited per client IP and per username.

## Sessions

Sessions renew on activity (sliding TTL, `SCREENLOOP_SESSION_TTL_SECONDS`) up to an absolute cap (`SCREENLOOP_SESSION_MAX_LIFETIME_SECONDS`, default 30 days). Every authenticated user can manage their own account:

- `POST /api/v1/me/password` with `{ "current_password": "...", "new_password": "..." }` — change own password. Revokes all other sessions of the user; the current session stays valid.
- `GET /api/v1/me/sessions` — list own active sessions (`ip`, `user_agent`, `created_at`, `last_seen_at`, `current`).
- `DELETE /api/v1/me/sessions` — revoke all own sessions except the current one.
- `DELETE /api/v1/me/sessions/{id}` — revoke one own session.

## Endpoint Groups

- `GET /api/v1/status`: live dashboard payload for polling.
- `GET /api/v1/version`: build version, revision, author, repository, and optional update state.
- `GET /api/v1/diagnostics`: admin-only runtime diagnostics without secrets.
- `GET /api/v1/media`, `POST /api/v1/media/upload`, `DELETE /api/v1/media/{id}`.
- `POST /api/v1/media/{id}/silent` with `{ "silent": true|false }` — toggle silent transcoded copies (re-runs all profiles).
- `GET/POST /api/v1/playlists`, `GET/DELETE /api/v1/playlists/{id}`.
- `POST /api/v1/playlists/{id}/items`, `DELETE /api/v1/playlist-items/{id}`, `POST /api/v1/playlist-items/{id}/move`.
- `POST /api/v1/playlist-items/{id}/position` with `{ "position": 0 }` — move an item to an absolute position (drag and drop).
- `GET/POST /api/v1/tvs`, `PATCH/DELETE /api/v1/tvs/{id}`.
- `GET /api/v1/tvs/scan`, `GET /api/v1/tvs/export`, `POST /api/v1/tvs/import`, `POST /api/v1/tvs/{id}/detect`.
- `POST /api/v1/tvs/{id}/commands` with `play_next`, `stop`, `restart_playlist`, `rediscover`, `mute`, or `unmute`.
- `GET /api/v1/transcode/jobs`, `POST /api/v1/transcode/jobs/{id}/rebuild`, `POST /api/v1/transcode/cleanup`.
- `GET /api/v1/events` (security audit entries are operator+).
- `GET/POST /api/v1/users`, `PATCH /api/v1/users/{id}` (the last active admin cannot be demoted or disabled).
- `POST /api/v1/users/{id}/password` with `{ "password": "...", "admin_password": "..." }` — admin resets another user's password and must confirm their own password.
- `POST /api/v1/me/password`, `GET/DELETE /api/v1/me/sessions`, `DELETE /api/v1/me/sessions/{id}` — see Sessions above.

## Nodes (remote sites)

Admin endpoints (session + CSRF):

- `POST /api/v1/nodes` with `{ "name": "..." }` — create a node; the response contains a one-time `enroll_token` (shown once, 24h TTL).
- `GET /api/v1/nodes` — list nodes with `enrolled`, `connected`, `tv_count`, `cache_used_bytes`, `last_seen`.
- `PATCH /api/v1/nodes/{id}` — rename; `DELETE /api/v1/nodes/{id}` — revoke and delete (TVs detach and go offline).
- `POST /api/v1/nodes/{id}/scan` — run SSDP discovery inside the node's network (waits up to 8s for the result).
- `POST`/`PATCH` on `/api/v1/tvs` accept `node_id` to assign a TV to a node; node TVs skip the local `SCREENLOOP_ALLOWED_TV_CIDRS` check.

Node endpoints (no session; authenticated by node token):

- `POST /api/v1/nodes/enroll` with `{ "enroll_token": "..." }` — exchange the one-time token for a permanent node token (stored hashed; rate-limited per IP).
- `GET /api/v1/nodes/media/{media_id}/{profile}` with `X-Node-Token` header — download a transcoded file (Range supported).
- `WS /api/v1/nodes/ws` with `Authorization: Bearer <node token>` — command/status transport. See [nodes.md](nodes.md).

## Frontend Rules

- Use `credentials: "same-origin"` for all API requests.
- Read a fresh CSRF token from `/api/v1/session` on app startup and after login.
- Never place stream tokens, session cookies, or passwords in logs.
- Treat `/api/health` as public and minimal; use `/api/v1/status` only after auth.
- Prefer polling `/api/v1/status` every 3-5 seconds before adding WebSockets/SSE.

## OpenAPI

Interactive documentation is available at:

- `/docs` for Swagger UI.
- `/redoc` for ReDoc.
- `/openapi.json` for generated clients.
