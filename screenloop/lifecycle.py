"""The life of a clip: draft -> published -> archived.

Deliberately not the same thing as `media.status`, which says what ffmpeg has
done with the file (`uploaded`, `processing`, `ready`, `failed`). A clip can be
`ready` and still be a `draft` nobody approved, and an `archived` clip keeps
its `ready` transcodes until somebody purges it. Conflating the two would mean
an approval could be undone by a re-encode.

Nothing here schedules anything, in the sense of a job: the airing window is a
pair of timestamps compared at the moment playback asks, so a clip starts and
stops on its own without anything needing to have run at the right second. That
matters for a controller that may be restarted, or asleep, when a campaign is
due to begin.
"""

from __future__ import annotations

import time
from typing import Any

DRAFT = "draft"
PUBLISHED = "published"
ARCHIVED = "archived"

STATES: tuple[str, ...] = (DRAFT, PUBLISHED, ARCHIVED)

# What a row with no opinion means. Every clip that existed before this column
# was already playing, so the upgrade default has to be `published` -- see the
# `_ensure_column` call in `store.init_schema`.
DEFAULT = PUBLISHED

# What an upload starts as. The approval gate is the point of the state: a
# branch uploads, an approver publishes.
ON_UPLOAD = DRAFT


def state(media: dict[str, Any] | None) -> str:
    """The stored state, falling back to the migration default.

    Rows outlive code: a state written by a later version, or a NULL left by a
    hand-edited database, must not crash the poll loop.
    """
    if not media:
        return DEFAULT
    value = str(media.get("lifecycle") or DEFAULT)
    return value if value in STATES else DEFAULT


def _timestamp(media: dict[str, Any] | None, field: str) -> int | None:
    if not media:
        return None
    raw = media.get(field)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def starts_at(media: dict[str, Any] | None) -> int | None:
    """When the clip is due on air. None means "as soon as it is published"."""
    return _timestamp(media, "starts_at")


def expires_at(media: dict[str, Any] | None) -> int | None:
    return _timestamp(media, "expires_at")


def is_expired(media: dict[str, Any] | None, now: float | None = None) -> bool:
    deadline = expires_at(media)
    if deadline is None:
        return False
    return (now if now is not None else time.time()) >= deadline


def has_not_started(media: dict[str, Any] | None, now: float | None = None) -> bool:
    opening = starts_at(media)
    if opening is None:
        return False
    return (now if now is not None else time.time()) < opening


def playable(media: dict[str, Any] | None, now: float | None = None) -> bool:
    """Whether this clip may go on a screen at all.

    A clip waiting for its start behaves exactly like an expired one, which
    behaves exactly like an archived one: the difference is only what the panel
    shows the operator. Approving a campaign a week early therefore does not put
    it on the screens a week early.
    """
    return state(media) == PUBLISHED and not is_expired(media, now) and not has_not_started(media, now)


def effective_state(media: dict[str, Any] | None, now: float | None = None) -> str:
    """What to label the clip with, airing window included. For display only."""
    current = state(media)
    if current != PUBLISHED:
        return current
    if is_expired(media, now):
        return "expired"
    if has_not_started(media, now):
        return "scheduled"
    return current
