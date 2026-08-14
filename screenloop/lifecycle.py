"""The life of a clip: draft -> published -> archived.

Deliberately not the same thing as `media.status`, which says what ffmpeg has
done with the file (`uploaded`, `processing`, `ready`, `failed`). A clip can be
`ready` and still be a `draft` nobody approved, and an `archived` clip keeps
its `ready` transcodes until somebody purges it. Conflating the two would mean
an approval could be undone by a re-encode.

Nothing here schedules anything: expiry is a timestamp compared at the moment
playback asks, so a clip that has run out simply stops being playable without a
job needing to have run.
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


def expires_at(media: dict[str, Any] | None) -> int | None:
    if not media:
        return None
    raw = media.get("expires_at")
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def is_expired(media: dict[str, Any] | None, now: float | None = None) -> bool:
    deadline = expires_at(media)
    if deadline is None:
        return False
    return (now if now is not None else time.time()) >= deadline


def playable(media: dict[str, Any] | None, now: float | None = None) -> bool:
    """Whether this clip may go on a screen at all.

    An expired clip behaves exactly like an archived one for playback; the
    difference is only what the panel shows the operator.
    """
    return state(media) == PUBLISHED and not is_expired(media, now)


def effective_state(media: dict[str, Any] | None, now: float | None = None) -> str:
    """What to label the clip with, expiry included. For display only."""
    current = state(media)
    if current == PUBLISHED and is_expired(media, now):
        return "expired"
    return current
