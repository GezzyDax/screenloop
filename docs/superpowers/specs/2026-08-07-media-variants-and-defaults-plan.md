# Media variants and upload defaults

Status: **planned, not started.** Written 2026-08-07.

## What was asked

1. Settings should carry defaults for new uploads — silent or with sound,
   compressed or not — so an operator does not set them per clip.
2. Better still: keep every variant on disk at once, so switching a clip
   between sound and silence, or between compressed and full, is instant
   instead of a transcode wait.

## Where this collides with what exists

Today `media.silent` and `media.compressed` are **booleans on the clip**, and
changing either **re-runs every profile's transcode** and throws the previous
output away (`web.py` → `api_set_media_silent`, `api_set_media_compressed`).
That is why switching costs a wait: the old file is deleted, not kept.

Output paths come from `transcode.output_path(source, profile, silent,
compressed)`, so the variants already have distinct filenames. Nothing keeps
more than one of them.

Storage on the production box today: 2.1 GB of originals producing 3.1 GB of
transcodes across 28 clips and 5 TVs. Two profiles are in use (`lg_webos`,
`samsung_legacy`).

## The cost of "store everything"

Variants multiply: profiles × silent × compressed. With two profiles in use
that is **4 combinations per clip** instead of the 2 stored now — transcoded
output roughly doubles, from 3.1 GB to about 6 GB. With all five shipped
profiles it would be 20 combinations and roughly 15 GB.

That is affordable at this scale but it is not free, and it is unbounded as
clips accumulate. So: build every variant **for the profiles actually assigned
to a TV**, never for all five, and make retention a setting rather than an
assumption.

## Plan

### Stage A — defaults for new uploads

Small, independent, delivers most of the everyday value.

- `settings` rows `media.default_silent` and `media.default_compressed`,
  reusing the table added with the schedule. Defaults `false`/`false`, so
  nothing changes for anybody on upgrade.
- `POST /api/v1/media/upload` applies them when the request does not say
  otherwise; the upload form gains explicit per-upload overrides.
- Settings page: a "Media defaults" block next to Operating hours.
- `GET/PUT /api/v1/settings/media` behind `media.manage`.

### Stage B — keep variants instead of replacing them

The part that removes the wait.

**Schema.** Replace the two booleans as the source of truth with a variants
table, keeping the columns as the *selected* variant so existing readers keep
working:

```sql
CREATE TABLE media_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    profile TEXT NOT NULL,
    silent INTEGER NOT NULL DEFAULT 0,
    compressed INTEGER NOT NULL DEFAULT 0,
    path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    size_bytes INTEGER,
    error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(media_id, profile, silent, compressed)
);
```

Backfill from the existing transcode output on first start: one row per file
already on disk, marked `ready`. No re-encoding on upgrade — that would be
hours of ffmpeg on a 3 GB library.

**Selection becomes free.** Toggling silent or compressed updates the media row
and, if that variant is `ready`, takes effect on the next push with no
transcode. If it is missing, it is queued and the current variant keeps
playing until the new one lands. Nothing is deleted on toggle.

**Which variants get built.** A setting decides:

- `selected` — only what is in use (today's behaviour, no extra storage);
- `sound` — both audio variants, compression as selected (the common case:
  "mute this screen now");
- `all` — every combination for profiles in use.

Per-profile, always: only profiles assigned to at least one TV. A profile
becoming assigned queues its missing variants.

**Retention.** `SCREENLOOP_MEDIA_VARIANT_BUDGET_BYTES` plus a cleanup pass that
drops the least recently used non-selected variants first. Without this the
directory grows without limit and the upload disk check starts failing.

### Stage C — UI

- Media page: per clip, show which variants exist and which is selected;
  switching a ready variant is instant and says so, a missing one shows the
  queue position.
- Storage line in Settings: variants on disk, total size, against the budget.

## Order and risk

A is independent and low risk — ship it first.

B touches the transcode pipeline, which is what puts pictures on screens, and
it changes the meaning of `media.silent`/`media.compressed`. It needs its own
release, and the production database has to be dry-run through the backfill
the way the permission engine was.

C follows B.

## Open questions to settle before starting B

- Does the ffmpeg audio-strip variant have to be a full re-encode, or can it be
  `-c:v copy -an` from the existing transcode? If copy works, the silent
  variant is nearly free in both time and CPU, which changes the storage
  calculation and probably makes `sound` the sensible default.
- Should a variant be built lazily on first request rather than eagerly on
  upload? Lazy costs one wait per combination ever, and nothing for
  combinations nobody uses.

## Not in scope

Per-TV variant overrides — a clip playing silent on one screen and with sound
on another. That needs the variant chosen at push time by TV, not stored on the
media row, and belongs with the group/scope work rather than here.
