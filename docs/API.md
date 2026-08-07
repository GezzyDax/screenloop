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

Access is decided by **permissions**, not by a role name. A role is a named set
of permissions; a user holds one or more roles and may do the union of what
they grant. `/api/v1/session` and the login response both report the caller's
effective permissions, and the panel renders from that list.

`viewer`, `operator` and `admin` ship as built-in roles holding exactly what
those names granted before permissions existed, so nothing about existing
access changed. Built-in roles cannot be edited or deleted.

- `viewer`: `tv.view`, `media.view`, `playlist.view`, `transcode.view`, `group.view`, `schedule.view`, `event.view`.
- `operator`: everything a viewer holds, plus `tv.command`, `media.upload`, `media.manage`, `playlist.edit`, `transcode.rebuild`, `event.security.view`.
- `admin`: the whole catalogue.

The catalogue lives in `screenloop/permissions.py`, not in the database: a
permission is a point in the code, and a stored one that no gate checks would
be undiscoverable rubbish. `tests/test_permissions.py` fails if the two drift
apart in either direction.

### Two rules that keep permissions from becoming an escalation path

Before this, anybody who could reach an administrative endpoint was already
all-powerful, so neither rule was needed. Both are enforced server-side:

- **You cannot grant authority you do not hold.** Creating or widening a role,
  assigning roles to a user, and setting a user's built-in role all refuse
  permissions missing from the caller's own set (`403`). Without it, a role
  carrying only `role.manage` could mint an all-powerful role for itself, and
  one carrying only `user.manage` could simply create an admin.
- **The installation must keep an administrator.** Editing, deleting, or
  unassigning a role is refused (`400`) when it would leave no enabled user
  holding `role.manage` or `user.manage`.

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
- `GET/POST /api/v1/tvs`, `PATCH/DELETE /api/v1/tvs/{id}`. `PATCH` also accepts `schedule_mode` (`inherit`, `always`, `custom`) and, for `custom`, `schedule_days` / `schedule_start` / `schedule_end`.
- `GET /api/v1/tvs/scan`, `GET /api/v1/tvs/export`, `POST /api/v1/tvs/import`, `POST /api/v1/tvs/{id}/detect`.
- `POST /api/v1/tvs/{id}/commands` with `play_next`, `stop`, `restart_playlist`, `rediscover`, `mute`, or `unmute`. Commands queued here are marked manual, which lets them through the operating window and clears a playback suspension.
- `POST /api/v1/tvs/{id}/resume` (operator) — clear a playback suspension. Returns `{"resumed": true|false}`; `false` when there was nothing to clear.
- `GET /api/v1/schedule` — the site-wide operating window plus `timezone`, `now`, `open`, and `next_open_at`.
- `PUT /api/v1/schedule` (admin) with `{ "enabled": true, "days": "0,1,2,3,4", "start": "08:00", "end": "20:00" }` — `days` is a comma-separated list where Monday is `0`. `400` for a malformed time, an out-of-range weekday, or equal start and end.
- `GET /api/v1/transcode/jobs`, `POST /api/v1/transcode/jobs/{id}/rebuild`, `POST /api/v1/transcode/cleanup`.
- `GET /api/v1/groups` — the TV group tree: each entry carries `depth`, `path`, `parent_id`, `tv_count`, and its `schedule_*` fields. Readable by any authenticated user.
- `POST /api/v1/groups` (`group.manage`) with `{ "name": "...", "parent_id": null }` — create a group. It also accepts `schedule_mode` (`inherit`, `always`, `custom`) and, for `custom`, `schedule_days` / `schedule_start` / `schedule_end`. `409` on a duplicate name under the same parent, `400` past the nesting cap or for an invalid window.
- `PATCH /api/v1/groups/{id}` (`group.manage`) — rename with `{ "name": "..." }`; re-parent with `{ "parent_id": ..., "move": true }`; or update the same four schedule fields. Omitted fields are preserved. Moving a group inside its own subtree returns `400`.
- `DELETE /api/v1/groups/{id}` (`group.manage`) — deletes the group and everything nested under it. TVs are not deleted; they become ungrouped.
- TVs carry an optional `group_id`, settable on `POST /api/v1/tvs` and `PATCH /api/v1/tvs/{id}`; `GET /api/v1/status` returns `group_name` alongside it.
- `GET /api/v1/profiles` (admin) — installed TV templates with `source: builtin|custom` plus the ids currently assigned to a TV.
- `GET /api/v1/profiles/catalog` (admin) — cached community index. Returns `{"enabled": false}` with no outbound request while `SCREENLOOP_COMMUNITY_CATALOG_CHECK` is off.
- `POST /api/v1/profiles/install` (admin) with `{ "url": "..." }` or `{ "catalog_id": "..." }` — fetch, validate, and install a template.
- `POST /api/v1/profiles/upload` (admin) — multipart `.toml` upload for offline installs.
- `DELETE /api/v1/profiles/{id}` (admin) — remove a custom template. `400` for a built-in id, `409` when it is assigned to a TV, `404` when it is not installed.
- `GET /api/v1/events` (security audit entries are operator+).
- `GET/POST /api/v1/users`, `PATCH /api/v1/users/{id}` (the last active admin cannot be demoted or disabled).
- `POST /api/v1/users/{id}/password` with `{ "password": "...", "admin_password": "..." }` — admin resets another user's password and must confirm their own password.
- `POST /api/v1/me/password`, `GET/DELETE /api/v1/me/sessions`, `DELETE /api/v1/me/sessions/{id}` — see Sessions above.
- `GET /api/v1/permissions` (`role.manage`) — the permission catalogue with titles, descriptions, and display sections.
- `GET/POST /api/v1/roles` (`role.manage`) — list roles with their permissions and user counts; create a role.
- `PATCH/DELETE /api/v1/roles/{id}` (`role.manage`) — `400` for a built-in role, a built-in name, or a change that would leave nobody able to administer; `409` for a duplicate name; `403` when granting beyond your own authority.
- `PUT /api/v1/users/{id}/roles` (`role.manage`) with `{ "assignments": [{ "role_id": 4, "scope_type": "group", "scope_id": 2 }] }` — replace the grants a user holds. `scope_type` is `global`, `group`, or `node`; the last two need `scope_id`. `403` when granting beyond your own scope, `400` for an unknown scope type or a missing id, `404` for an unknown group or node.

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

## Scopes

A grant is a role **plus where it applies**. `global` covers everything; a
`group` grant covers that group and its whole subtree, so a grant on a branch
reaches the floors beneath it; a `node` grant covers the screens attached to
that node. Groups and nodes are independent axes — a screen has both, and
either can carry the grant.

Everything from before scopes exists became `global`, so no existing access
changed.

**Filtering is the substance, not the gates.** `/api/v1/status`, `/api/v1/tvs`,
the SSE snapshot, `/api/v1/groups`, `/api/v1/nodes` and `/api/v1/events` all
return only what the caller's scopes cover. Without that a branch operator
could be refused a command and still read every screen's name, address and
current clip off the dashboard. Group listings additionally keep the ancestors
of anything visible, or a branch would render at the root with no context.

Object-level gates answer "over this particular screen": commanding, editing,
deleting, detecting, resuming. Moving a screen into a group, or creating one
there, needs authority over the **destination** as well — otherwise a branch
administrator could push their screens into somebody else's tree.

Two rules carry over from the permission engine and gain a scope:

- **You cannot grant beyond your own scope.** Granting `tv.manage` on a branch
  requires holding it globally or on that branch or one of its ancestors.
- **The last-administrator checks count global grants only.** Somebody confined
  to one branch cannot administer the installation, so they do not satisfy
  "somebody still holds `role.manage`".

## Operating Hours

DLNA has no power command, and the UPnP spec requires a renderer to leave standby to service `Play` — so the only lever over a screen's duty cycle is not sending it anything. Two mechanisms use that lever:

- **The schedule.** Outside its window a TV is stopped once and then left alone. Disabled by default: an upgrade never starts blanking screens on its own. The effective window is selected in this order: **TV override → nearest non-inheriting group → ancestor groups → site schedule**. On both TVs and groups, `always` stops inheritance and opts out entirely, while `custom` defines a weekly window. Moving a group changes the inherited schedule immediately; the same resolved window is enforced by local workers and remote nodes.
- **Suspension.** A TV that reports `NO_MEDIA_PRESENT` for `SCREENLOOP_MANUAL_OFF_CONFIRMATIONS` consecutive polls while it still has media assigned is treated as switched off by a person — Samsung and LG clear the AVTransport instance when they enter standby. Playback is suspended and no push is sent until either the next window opens or somebody resumes it.

Both are reported per TV in `/api/v1/status`: `schedule_open`, `schedule_next_open_at`, `playback_suspended`.

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
