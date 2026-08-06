# Group Schedule Inheritance Design

## Goal

Allow an administrator to define operating hours once on any TV group and
have every TV below that point in the group tree inherit them, while retaining
the existing site-wide schedule and per-TV overrides.

The effective schedule is resolved in this order:

1. The TV.
2. Its directly assigned group.
3. Each ancestor group, from nearest to farthest.
4. The site-wide schedule.

The first level whose mode is not `inherit` wins. `always` means unrestricted
playback and stops traversal just like `custom`. An ungrouped TV in `inherit`
mode falls directly through to the site-wide schedule.

## Scope

This change adds schedule settings to existing groups, exposes them through
the group API and TV management UI, and makes the worker enforce the resolved
schedule for every TV.

It does not add multiple windows per day, calendars, exceptions, holidays,
timezone overrides per group, or bulk materialisation of group settings onto
TV rows. Every window continues to use the single configured Screenloop
timezone.

## Data Model

`tv_groups` gains the same four scheduling columns already present on `tvs`:

- `schedule_mode TEXT NOT NULL DEFAULT 'inherit'`
- `schedule_days TEXT`
- `schedule_start TEXT`
- `schedule_end TEXT`

Existing groups therefore inherit without migration-time behaviour changes.
SQLite schema upgrades use the existing `_ensure_column` mechanism.

Group settings remain attached to the group when it is renamed or moved. If a
group is moved, its descendants immediately inherit through the new ancestor
chain. Deleting a group keeps the existing deletion semantics; TVs detached by
the deletion fall back to the site-wide schedule unless they have a per-TV
override.

## Schedule Resolution

Schedule parsing remains in `screenloop/schedule.py`. A small resolver accepts
a TV, its ordered group chain, and the global settings. It examines the TV and
groups in precedence order and returns the first `always` or valid `custom`
window. If every level inherits, it returns the global window.

Invalid stored custom data can only arise from direct database modification or
an old incompatible writer because API writes are validated. Such a level is
treated as `inherit`, logged with its entity type and ID, and resolution
continues upward. This preserves the existing safe fallback behaviour instead
of making playback unrestricted.

The store returns each TV with its group ancestry's schedule fields in a
structured chain. The worker resolves a schedule per TV during its existing
poll cycle. Group settings are not copied into TV records and do not require a
separate worker cache, so a saved group change is visible on the next poll.

## API

The existing group response includes:

- `schedule_mode`
- `schedule_days`
- `schedule_start`
- `schedule_end`

`GroupCreateRequest` and `GroupUpdateRequest` accept the same fields. Create
defaults to `inherit`. Patch semantics distinguish omitted schedule fields from
explicit values, so renaming or moving a group cannot accidentally reset its
schedule.

For `inherit` and `always`, custom day/time values are cleared. For `custom`,
days, start, and end are required and validated through the existing schedule
parser. Invalid modes or unusable windows return HTTP 400 without partially
renaming, moving, or changing the group. Group mutations therefore remain
atomic.

Only administrators may change group schedules, matching current group
management permissions. Authenticated viewers can read them as part of the
group tree.

## User Interface

The group table on the TV management page gains a schedule control for every
group. It offers the same three modes used by TVs:

- inherit from the parent group or site;
- always on;
- custom operating hours.

Selecting `custom` reveals weekday and start/end controls. Saving uses the
existing pending-action and toast patterns. The group path and indentation
make clear which parent supplies inherited settings. Existing per-TV controls
remain unchanged; their `inherit` label is updated to make clear that it now
means the nearest group first, then the site schedule.

No separate schedule page or new frontend dependency is introduced.

## Runtime Behaviour

The worker continues to enforce schedules one TV at a time:

- outside the effective window it queues one `stop` and leaves the renderer
  alone;
- when a later window opens it clears schedule-created suspension according to
  the existing rules;
- `always` at the TV or winning group level permits playback regardless of
  ancestor and global windows;
- moving a TV or group changes the effective window on the next poll.

The status and TV APIs expose the effective open state and next opening time
using the same resolver as the worker, preventing UI/runtime disagreement.

## Testing

Unit tests cover resolver precedence and fallback:

- TV custom and TV always override every group;
- the nearest non-inheriting group wins;
- an inheriting child group falls through to its parent;
- an ungrouped inheriting TV uses the global schedule;
- invalid stored group data falls through safely;
- moving a TV or group changes the resolved schedule without copying fields.

Store and API tests cover schema defaults, round trips, validation, permissions,
partial updates, and atomic failure. Worker tests prove group closing and
reopening behaviour. Frontend tests prove that rename/move payloads preserve
schedule fields and that schedule-only updates preserve group identity.

The full Python suite, frontend tests/build, lint, type checking, Docker image
builds, Trivy scans, and smoke test must pass before the pull request is merged
into `dev`.
