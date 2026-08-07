"""Operating hours for TV playback.

A TV that is not being pushed to is a TV that stays off. That is the whole
point of this module: DLNA has no power command, but the UPnP spec requires a
renderer to leave standby to service `Play`, so *not* sending `Play` is the
only lever there is over a screen's duty cycle.

A schedule is one weekly window: a set of weekdays plus a start and an end
time. `22:00-06:00` is allowed and belongs to the day it starts on, so a window
on Friday night runs into Saturday morning without Saturday being selected.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from . import config

logger = logging.getLogger("screenloop.schedule")

# Monday is 0, matching datetime.weekday().
WEEKDAYS = (0, 1, 2, 3, 4, 5, 6)
WORKWEEK = frozenset({0, 1, 2, 3, 4})
EVERY_DAY = frozenset(WEEKDAYS)


class ScheduleError(ValueError):
    """A schedule that cannot be applied, reported back to the caller."""


@dataclass(frozen=True)
class Window:
    days: frozenset[int]
    start: dt.time
    end: dt.time

    @property
    def overnight(self) -> bool:
        return self.end <= self.start

    def is_open(self, now: dt.datetime) -> bool:
        if not self.days:
            return False
        moment = now.time()
        if not self.overnight:
            return now.weekday() in self.days and self.start <= moment < self.end
        # The window is anchored to the day it opens on, so before `end` we are
        # still inside yesterday's window.
        if now.weekday() in self.days and moment >= self.start:
            return True
        return (now.weekday() - 1) % 7 in self.days and moment < self.end

    def next_open_at(self, now: dt.datetime) -> dt.datetime | None:
        """When the window next opens, or None if it never does."""
        if not self.days:
            return None
        for offset in range(8):
            day = now.date() + dt.timedelta(days=offset)
            if day.weekday() not in self.days:
                continue
            opens_at = dt.datetime.combine(day, self.start, tzinfo=now.tzinfo)
            if opens_at > now:
                return opens_at
        return None

    def opened_at(self, now: dt.datetime) -> dt.datetime | None:
        """When the window currently containing `now` opened.

        Lets the worker decide whether a suspension predates the current
        window without keeping any state of its own, which matters because
        that state would otherwise be lost on every restart.
        """
        if not self.is_open(now):
            return None
        if not self.overnight or now.time() >= self.start:
            return dt.datetime.combine(now.date(), self.start, tzinfo=now.tzinfo)
        return dt.datetime.combine(now.date() - dt.timedelta(days=1), self.start, tzinfo=now.tzinfo)

    def closes_at(self, now: dt.datetime) -> dt.datetime | None:
        """When the window currently containing `now` closes."""
        if not self.is_open(now):
            return None
        if not self.overnight:
            return dt.datetime.combine(now.date(), self.end, tzinfo=now.tzinfo)
        if now.time() >= self.start:
            return dt.datetime.combine(now.date() + dt.timedelta(days=1), self.end, tzinfo=now.tzinfo)
        return dt.datetime.combine(now.date(), self.end, tzinfo=now.tzinfo)


def parse_time(value: str) -> dt.time:
    text = (value or "").strip()
    try:
        hour_text, _, minute_text = text.partition(":")
        hour, minute = int(hour_text), int(minute_text)
    except ValueError:
        raise ScheduleError(f"Time must look like HH:MM, got {value!r}") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError(f"Time must be between 00:00 and 23:59, got {value!r}")
    return dt.time(hour, minute)


def format_time(value: dt.time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def parse_days(value: str | None) -> frozenset[int]:
    """Parse "0,1,2,3,4" into a weekday set. Empty means no day is selected."""
    if value is None:
        return EVERY_DAY
    days = set()
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            day = int(part)
        except ValueError:
            raise ScheduleError(f"Weekday must be a number 0-6, got {part!r}") from None
        if day not in WEEKDAYS:
            raise ScheduleError(f"Weekday must be 0 (Monday) to 6 (Sunday), got {day}")
        days.add(day)
    return frozenset(days)


def format_days(days: frozenset[int]) -> str:
    return ",".join(str(day) for day in sorted(days))


def build_window(days: str | None, start: str, end: str) -> Window:
    parsed_start = parse_time(start)
    parsed_end = parse_time(end)
    if parsed_start == parsed_end:
        raise ScheduleError("Start and end must differ; use a 00:00-23:59 window for all day")
    return Window(days=parse_days(days), start=parsed_start, end=parsed_end)


INHERIT = "inherit"
ALWAYS = "always"
CUSTOM = "custom"
MODES = (INHERIT, ALWAYS, CUSTOM)


def global_window(settings: dict) -> Window | None:
    """The site-wide window, or None when no schedule is configured."""
    if not settings.get("enabled"):
        return None
    try:
        return build_window(settings.get("days"), settings.get("start", ""), settings.get("end", ""))
    except ScheduleError:
        logger.warning("global schedule is not usable, treating playback as unrestricted: %r", settings)
        return None


def _source_window(source: dict, source_type: str) -> tuple[bool, Window | None]:
    """Return whether a source overrides its parent and the resulting window."""
    mode = (source.get("schedule_mode") or INHERIT).strip()
    if mode == INHERIT:
        return False, None
    if mode == ALWAYS:
        return True, None
    if mode == CUSTOM:
        try:
            return True, build_window(
                source.get("schedule_days"),
                source.get("schedule_start") or "",
                source.get("schedule_end") or "",
            )
        except ScheduleError:
            logger.warning(
                "%s %s has an unusable custom schedule, continuing inheritance",
                source_type,
                source.get("id"),
            )
    return False, None


def resolve_window(tv: dict, settings: dict) -> Window | None:
    """The inherited window governing one TV, or None when unrestricted."""
    sources = [("TV", tv)]
    sources.extend(("TV group", group) for group in tv.get("schedule_groups") or [])
    for source_type, source in sources:
        resolved, window = _source_window(source, source_type)
        if resolved:
            return window
    return global_window(settings)


def playback_allowed(tv: dict, settings: dict, moment: dt.datetime | None = None) -> bool:
    window = resolve_window(tv, settings)
    if window is None:
        return True
    return window.is_open(moment or now())


def now() -> dt.datetime:
    """Local time in the configured timezone.

    The schedule is what people read off a wall clock, so it has to follow the
    site's timezone rather than the container's, which is UTC by default.
    """
    return dt.datetime.now(config.timezone())
