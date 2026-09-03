"""
ICS (iCalendar) feed parsing.

Fallback path for when a Canvas API token isn't available (some
institutions lock down self-service token generation entirely). Most
Canvas instances still expose a private per-user calendar feed URL
(Calendar page -> "Calendar Feed", or a course's Syllabus page) that
works with no token at all, since it's designed for subscribing in an
external calendar app.

This gets due dates and scheduled events -- it does NOT get grades,
submission status, or anything the REST API exposes beyond what's on
a calendar. It's a real fallback, not a full replacement for
CanvasClient/CanvasSyncWorker.

All datetimes are normalized to naive UTC before leaving this module,
per the project-wide convention (see asos.db.base._now) -- ICS feeds
can supply timezone-aware datetimes or bare dates for all-day events,
and both need to end up in the same normalized form everything else
in the schema expects.
"""

from __future__ import annotations

import dataclasses
import datetime

from icalendar import Calendar


@dataclasses.dataclass
class ParsedICSEvent:
    uid: str
    title: str
    start_at: datetime.datetime
    end_at: datetime.datetime | None
    description: str | None


def _normalize_to_naive_utc(value: datetime.date | datetime.datetime) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        if value.tzinfo is not None:
            return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return value
    # A bare date (all-day event, e.g. a due-date-only calendar entry).
    return datetime.datetime(value.year, value.month, value.day)


def parse_ics(ics_text: str) -> list[ParsedICSEvent]:
    """Parses raw ICS text into a list of events. Events with no
    DTSTART are skipped (nothing sensible to place them at) rather
    than raising -- a feed with one malformed entry shouldn't block
    every other valid event in it."""
    calendar = Calendar.from_ical(ics_text)
    events: list[ParsedICSEvent] = []

    for component in calendar.walk("VEVENT"):
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue

        uid = str(component.get("UID"))
        title = str(component.get("SUMMARY")) if component.get("SUMMARY") else "Untitled event"
        start_at = _normalize_to_naive_utc(dtstart.dt)

        dtend = component.get("DTEND")
        end_at = _normalize_to_naive_utc(dtend.dt) if dtend else None

        description_field = component.get("DESCRIPTION")
        description = str(description_field) if description_field else None

        events.append(ParsedICSEvent(uid=uid, title=title, start_at=start_at, end_at=end_at, description=description))

    return events
