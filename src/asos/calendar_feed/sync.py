"""
ICS feed fetching and sync.

Fetching is a thin, injectable wrapper (same DI pattern as
CanvasClient) so tests never need real network access. Syncing
mirrors CanvasSyncWorker's calendar-event upsert logic: new events are
created and logged, changed fields on known events are diffed and
logged with the old value retained -- same sync_change_log audit
trail Canvas sync uses, since this is just a second writer into the
same calendar_events table.
"""

from __future__ import annotations

import logging
from typing import Protocol

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from asos.calendar_feed.parsing import parse_ics
from asos.db.enums import CalendarEventSource, CalendarEventType, SyncChangeType, SyncEntityType
from asos.db.models import CalendarEvent, SyncChangeLogEntry

logger = logging.getLogger("asos.calendar_feed")

_TRACKED_FIELDS = ("title", "start_at", "end_at")


class ICSFetchError(RuntimeError):
    pass


class HttpSession(Protocol):
    def get(self, url: str, timeout: float = ...): ...


def fetch_ics(url: str, session: HttpSession | None = None, timeout: float = 15.0) -> str:
    session = session or requests
    try:
        response = session.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise ICSFetchError(f"Network error fetching ICS feed: {exc}") from None

    if response.status_code != 200:
        raise ICSFetchError(f"ICS feed returned HTTP {response.status_code}")

    return response.text


def _log_change(session: Session, *, entity_id: int, external_id: str, change_type: SyncChangeType, field_name=None, old_value=None, new_value=None) -> None:
    session.add(
        SyncChangeLogEntry(
            entity_type=SyncEntityType.CALENDAR_EVENT,
            entity_id=entity_id,
            external_id=external_id,
            change_type=change_type,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
        )
    )


def sync_ics_text(session: Session, ics_text: str, *, course_id: int | None = None) -> dict:
    """Parses and reconciles ICS text against local calendar_events.
    Returns a small summary dict, same shape spirit as
    CanvasSyncWorker.sync_all()."""
    parsed_events = parse_ics(ics_text)
    created_count = 0
    changes_detected = 0

    for pe in parsed_events:
        existing = session.execute(
            select(CalendarEvent).where(CalendarEvent.external_event_id == pe.uid)
        ).scalar_one_or_none()

        new_values = {"title": pe.title, "start_at": pe.start_at, "end_at": pe.end_at}

        if existing is None:
            event = CalendarEvent(
                course_id=course_id,
                source=CalendarEventSource.ICS_FEED,
                external_event_id=pe.uid,
                event_type=CalendarEventType.OTHER,
                **new_values,
            )
            session.add(event)
            session.flush()
            _log_change(session, entity_id=event.id, external_id=pe.uid, change_type=SyncChangeType.CREATED)
            created_count += 1
            changes_detected += 1
        else:
            for field_name in _TRACKED_FIELDS:
                old = getattr(existing, field_name)
                new = new_values[field_name]
                if old != new:
                    _log_change(
                        session,
                        entity_id=existing.id,
                        external_id=pe.uid,
                        change_type=SyncChangeType.UPDATED,
                        field_name=field_name,
                        old_value=str(old) if old is not None else None,
                        new_value=str(new) if new is not None else None,
                    )
                    setattr(existing, field_name, new)
                    changes_detected += 1

    session.commit()
    return {"events_seen": len(parsed_events), "created": created_count, "changes_detected": changes_detected}
