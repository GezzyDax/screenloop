# Community TV templates — design

## Context

Screenloop currently supports exactly five TV profiles, hardcoded as a Python
dict in `screenloop/profiles.py` (`lg_netcast`, `generic_dlna`, `lg_webos`,
`samsung_tizen`, `samsung_legacy`). Each profile bundles the ffmpeg transcode
settings, DLNA mime type/protocol info, and vendor-match keywords needed to
push TV-safe video to a given renderer. Adding support for a new TV model
today requires editing this Python file and shipping a new backend release.

DLNA/UPnP renderers span hundreds of vendor/firmware combinations, each with
its own ceilings for bitrate, H.264 profile/level, resolution and FPS. The
maintainers cannot obtain or test against most of this hardware — only
someone who actually owns a given TV can determine working settings for it.

This design adds a template engine, modeled on the Pterodactyl "eggs"
pattern: TV profiles become plain-text, human-editable template files
instead of Python code, anyone can drop one in locally for their own
unsupported TV, and a separate community repository lets contributors PR
new templates without ever touching Screenloop's codebase. The app can
browse and install from that repository, or import a single template file
by URL/upload for admins who prefer not to enable outbound network calls.

## Goals

- Turn `screenloop/profiles.py` into a generic template engine — no
  TV-specific data hardcoded in Python. The five current profiles become
  bundled `.toml` templates using the exact same schema/engine as
  community-contributed ones.
- Let an admin add support for an unsupported TV without a code change:
  drop a `.toml` file locally, import one by URL/file upload, or install
  one from an opt-in community catalog browser in the UI.
- Fail loudly and specifically on a malformed template (missing/invalid
  field) at load/import time, never a raw `KeyError` deep inside
  `transcode.py`.
- Keep the change scoped: reuse the existing `PROFILES` dict shape and every
  existing call site (`worker.py`, `transcode.py`, `web.py`, `node_agent.py`)
  unchanged in behavior — only how `PROFILES` gets populated changes.

## Non-goals

- No automatic background sync/polling of the community repo — catalog
  fetch only happens opt-in, on-demand from the UI, mirroring the existing
  `SCREENLOOP_UPDATE_CHECK` pattern.
- No moderation/trust system beyond basic schema validation — the community
  repo's own PR review is the trust boundary, same as any other
  community-maintained config repository (Pterodactyl eggs, Homebrew casks).
- No per-TV override of an installed template's settings — a template is
  still selected by key per TV, same as today. Per-TV field overrides are
  out of scope for this design.
- No YAML — TOML was chosen instead (see Format decision below).

## Format decision: TOML

TOML over YAML/JSON, because:

- Python 3.13 (this project's target) has `tomllib` in the standard library
  — zero new dependency. YAML would require adding `PyYAML`.
- Templates are untrusted input from strangers on the internet by design.
  TOML has no code-execution/object-construction primitives (unlike YAML's
  classic loader); there is no "did we remember `safe_load`" question to
  get right.
- TOML is flat and unambiguous — no indentation-sensitivity bugs, no
  `no`/`yes`/`on` boolean surprises — easier for a non-programmer TV owner
  to hand-edit correctly by copying an example.
- Comments are supported (unlike JSON), useful for a `# tested on firmware
  X.Y` note inline.

## Template schema

One file = one TV profile. `id` is the filename (sans `.toml`), not a field
inside the file — this makes the on-disk filename authoritative and avoids
a class of path-traversal/spoofing bugs where a file's declared id disagrees
with where it's stored.

```toml
name = "Sony Bravia X-series"
match = ["sony", "bravia"]
priority = 0                    # optional, default 0; higher checked first in detect_profile
mime_type = "video/mp4"
dlna_protocol_info = "http-get:*:video/mp4:DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000"  # optional
probe_port = 52323               # optional, default 9197 — cheap reachability heuristic only, see below

[ffmpeg]
video_codec = "libx264"          # required, allow-listed
h264_profile = "high"            # optional, default "high"
h264_level = "4.1"               # optional, default "4.1"
audio_codec = "aac"              # required, allow-listed
audio_sample_rate = 48000        # optional, default 48000
max_width = 1920                 # required
max_height = 1080                # required
target_width = 1920              # optional, defaults to max_width
target_height = 1080             # optional, defaults to max_height
exact_frame = true               # optional, default false
fps = 30                         # required
crf = 22                         # required
maxrate = "12000k"               # required
bufsize = "24000k"               # required
audio_bitrate = "160k"           # required

[meta]                           # optional, purely descriptive, not consumed by transcode/DLNA logic
author = "github-handle"
tested_on = "Sony Bravia XR-55A80L, firmware PKG6.7370"
notes = "Needs exact 30fps padding or playback stutters"
```

`probe_port` note: it is *only* a pre-flight TCP reachability check in
`worker.poll_tv` (`worker.py:209-210`), never used by SSDP discovery or by
the SOAP control path — a wrong value causes at most a one-cycle "offline"
flicker before the app self-heals via real SSDP rediscovery
(`worker.py:300-319`). It is optional in the schema for this reason;
authors do not need to get it exactly right.

## Engine architecture

- **`screenloop/builtin_templates/*.toml`** — the current 5 profiles,
  transcribed verbatim into the schema above. Shipped with the app,
  read-only: cannot be deleted or overwritten via the API.
- **`data_dir/profiles/*.toml`** — user-installed custom/community
  templates (new subdirectory alongside existing `media/`, `transcoded/`,
  `db/`). Writable via the API (import by URL, upload, catalog install,
  delete).
- **`screenloop/profiles.py`** becomes the loader/engine:
  - `load_profiles()` scans both directories, parses each file with
    `tomllib`, runs `validate_template()`, and builds the merged `PROFILES`
    dict keyed by filename-derived id, each entry tagged
    `source: "builtin" | "custom"`.
  - A custom template whose id collides with a builtin id is rejected
    (builtin protection).
  - `PROFILES` stays a **module-level dict that is mutated in place**
    (`.clear()` + `.update()`) rather than reassigned, so every existing
    `from .profiles import PROFILES` import across `worker.py`,
    `transcode.py`, `web.py`, `node_agent.py` keeps seeing live data with no
    changes to those call sites.
  - `reload_profiles()` is called at startup and again after any
    install/upload/delete via the API — no app restart required.
  - `detect_profile()`/`profile_or_default()` keep their current signatures
    and behavior, just operating over the merged dict. The existing
    Samsung legacy-vs-tizen special case
    (`"samsung" in haystack and "tizen" not in haystack`) stays as engine
    logic tied to those two specific builtin templates. New ambiguous
    overlaps between community templates are resolved via the optional
    `priority` field rather than generalizing the match syntax further.

Packaging check: the project has no `setup.py`/packaging step anywhere —
`Dockerfile` does a full `COPY screenloop ./screenloop` directory copy, and
local dev/CI run `python -m screenloop` straight from the checkout. A new
`screenloop/builtin_templates/` directory ships correctly with zero
packaging changes.

## Validation (`validate_template`)

Runs on every file at load time (builtin and custom) and on every
API-driven import, returning a list of human-readable errors instead of
letting a bad template reach `transcode.py` as a raw `KeyError`.

- Required: `name`, `[ffmpeg].video_codec`, `audio_codec`, `max_width`,
  `max_height`, `fps`, `crf`, `maxrate`, `bufsize`, `audio_bitrate`.
- `dlna_protocol_info` is optional — `dlna.make_didl()` already has a safe
  fallback (`dlna.py:325`), so the schema doesn't need to force it.
- Type/range checks: `crf` int 0–51, `max_width`/`max_height` sane bounds
  (e.g. 320–3840), `fps` int 1–60, `probe_port` int 1–65535.
- `video_codec`/`audio_codec` are allow-listed (`libx264`, `aac`) rather
  than free strings — `transcode.py` always builds an argv list for
  `subprocess.run` with no `shell=True`, so there's no injection vector,
  but an allow-list stops a broken/malicious template from producing a
  silently-wrong ffmpeg invocation.
- id (filename) must match `^[a-z0-9_]{1,40}$` and not collide with a
  builtin id.
- File size capped (~16 KB) before parsing; a fetched-by-URL/catalog
  template is capped and time-limited on download too.

## Companion fix: scope transcode-on-upload to profiles in use

Today, `save_upload()` (`web.py:647-648`) does:

```python
for profile in PROFILES:
    store.ensure_transcode_job(media_id, profile)
```

— every uploaded video gets a full ffmpeg transcode queued for *every*
profile in `PROFILES`, unconditionally, regardless of whether any TV uses
that profile (confirmed: `store.next_transcode_job()` drains the queue FIFO
with no join against `tvs.profile`). With only 5 built-in profiles this is
already wasteful; with an open-ended number of community templates
installed locally it would multiply transcode cost per upload without
bound.

Fix: change the loop to only `ensure_transcode_job` for profiles currently
assigned to at least one existing TV (distinct `tvs.profile` values) plus
`generic_dlna` as the safe default. The existing lazy path in
`Worker.is_item_playable` (`worker.py:497-518`, already calls
`ensure_transcode_job` on demand) backfills the job automatically the first
time a TV is switched to or created with a profile that has no job yet —
this path already exists and needs no changes.

## Community catalog

A separate GitHub repository (not part of this codebase) holds:

- `templates/*.toml` — one file per contributed TV, same schema as above,
  contributed via PR.
- `index.json` at the repo root — a flat list of
  `{id, name, vendor, author, description, file}` entries, so the app can
  fetch one small file instead of walking the GitHub Contents API per
  template.

### Backend

New config in `config.py`, mirroring the existing `SCREENLOOP_UPDATE_CHECK`
pattern exactly (`web.py:211-238`, guard-before-network, module-level TTL
cache, broad `except Exception` caching the error so a network outage
doesn't cause a retry storm):

- `SCREENLOOP_COMMUNITY_CATALOG_CHECK` — bool, default `false` (opt-in).
- `SCREENLOOP_COMMUNITY_CATALOG_URL` — default points at the community
  repo's `index.json`.
- `SCREENLOOP_COMMUNITY_CATALOG_CACHE_SECONDS` — default `3600`.

New admin-only, CSRF-protected routes:

- `GET /api/v1/profiles` — merged list of installed profiles
  (`id`, `name`, `source: builtin|custom`, match, mime info) for the
  management UI.
- `GET /api/v1/profiles/catalog` — cached community index; returns
  `{"enabled": false}` immediately if the config flag is off, no network
  call attempted (same short-circuit as `latest_release_version()`).
- `POST /api/v1/profiles/install` — body is either `{"catalog_id": ...}`
  (resolved against the cached catalog) or `{"url": ...}` (direct import —
  works even when the catalog flag is off, since it's an explicit one-shot
  admin action, not background polling). Fetches, validates, writes to
  `data_dir/profiles/<id>.toml`, calls `reload_profiles()`, audit-logs
  `profile_installed`.
- `POST /api/v1/profiles/upload` — multipart file variant for fully
  offline admins.
- `DELETE /api/v1/profiles/{id}` — rejects builtin ids and any custom
  template currently assigned to a TV; audit-logs `profile_deleted`.

### Frontend

- `TvsView.vue`'s existing profile `<select>` (currently shows the raw dict
  key as the label) switches to showing `profile.name`, with a badge for
  builtin vs custom.
- New "Templates" panel: list of installed profiles with delete for custom
  ones; a community catalog browser (shown only when the catalog endpoint
  reports `enabled: true`, otherwise a hint to enable the config flag) with
  an Install button per entry; an always-available "Import by URL / upload
  file" form, surfacing backend validation errors inline.
- New i18n strings (en/ru) following the existing `warningUpdateCheck`
  pattern.

## Security summary

- TOML has no code-execution primitives (the primary reason it was chosen
  over YAML for this specific untrusted-input use case).
- ffmpeg invocation is already argv-list based with no `shell=True`
  (`transcode.py:157-219`) — template field values cannot inject shell
  commands; allow-lists/ranges exist to stop resource-abuse (absurd
  bitrate/resolution) and confusing failures, not injection.
- Outbound catalog fetch is opt-in, default off, consistent with the
  project's LAN-first stance and the existing `SCREENLOOP_UPDATE_CHECK`
  precedent. Manual import-by-URL/upload is an explicit, one-shot,
  CSRF-protected admin action available regardless of that flag.
- Downloaded content (catalog index and individual templates) is
  size-capped and time-limited.
- Filename-derived ids are regex-validated before ever touching the
  filesystem, preventing path traversal into `data_dir/profiles/`.
- Install/delete are audit-logged like other admin actions
  (`events.py`).

## Testing

- `tests/test_core.py`: template loading (valid/invalid TOML),
  `validate_template` edge cases (missing required field, out-of-range
  value, id/builtin collision, oversized file), merged `PROFILES`
  correctness after `reload_profiles()`, `detect_profile` still passing
  with the `priority` field in play.
- `tests/test_api.py`: `GET /api/v1/profiles` role gating; `POST
  /api/v1/profiles/install` from a mocked URL and from a mocked catalog
  entry; `POST /api/v1/profiles/upload` multipart; `DELETE
  /api/v1/profiles/{id}` blocked for builtin ids and for in-use custom
  ids; `GET /api/v1/profiles/catalog` returns `{"enabled": false}` with no
  network call when the config flag is off; upload endpoint only queues
  transcode jobs for profiles in use.
- Per project convention, DLNA/playback behavior itself should still be
  manually verified against at least one real TV once a template is in
  use — not automatable.

## Verification

- `python3 -m unittest discover -s tests` covering the new/changed
  behavior above.
- Manual: install a custom template via URL import and via file upload in
  a running dev instance, assign it to a TV, confirm playback pushes with
  the template's ffmpeg/DLNA settings; confirm a deliberately broken
  template is rejected with a specific validation error instead of a raw
  exception; confirm upload no longer queues transcode jobs for unused
  profiles.
