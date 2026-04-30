# Screenloop API

Screenloop exposes a JSON API under `/api/v1` for the future Vue UI and trusted LAN integrations. The API uses the same hardened security model as the server-rendered UI.

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

- `viewer`: read-only status, media, playlists, TVs, events, transcode jobs.
- `operator`: viewer access plus playback commands, playlist edits, media upload, transcode rebuilds.
- `admin`: full access, including users, TV config, delete/import/export, cache cleanup.

The API returns `401` for missing/invalid sessions, `403` for missing CSRF or insufficient role, and `429` for rate-limited actions.

## Endpoint Groups

- `GET /api/v1/status`: live dashboard payload for polling.
- `GET /api/v1/media`, `POST /api/v1/media/upload`, `DELETE /api/v1/media/{id}`.
- `POST /api/v1/media/{id}/silent` with `{ "silent": true|false }` — toggle silent transcoded copies (re-runs all profiles).
- `GET/POST /api/v1/playlists`, `GET/DELETE /api/v1/playlists/{id}`.
- `POST /api/v1/playlists/{id}/items`, `DELETE /api/v1/playlist-items/{id}`, `POST /api/v1/playlist-items/{id}/move`.
- `GET/POST /api/v1/tvs`, `PATCH/DELETE /api/v1/tvs/{id}`.
- `GET /api/v1/tvs/scan`, `GET /api/v1/tvs/export`, `POST /api/v1/tvs/import`, `POST /api/v1/tvs/{id}/detect`.
- `POST /api/v1/tvs/{id}/commands` with `play_next`, `stop`, `restart_playlist`, `rediscover`, `mute`, or `unmute`.
- `GET /api/v1/transcode/jobs`, `POST /api/v1/transcode/jobs/{id}/rebuild`, `POST /api/v1/transcode/cleanup`.
- `GET /api/v1/events`.
- `GET/POST /api/v1/users`, `PATCH /api/v1/users/{id}`, `POST /api/v1/users/{id}/password`.

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
