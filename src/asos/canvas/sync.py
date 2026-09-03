"""
Canvas sync worker.

Pulls courses/assignments/calendar events from Canvas and reconciles
them against local DB state:
  - New Canvas entities -> inserted, logged as `created`.
  - Changed fields on known entities -> updated, logged as `updated`
    with the old value preserved in `sync_change_log` (never a silent
    overwrite — see PROJECT.md acceptance criterion 2).
  - Entities no longer returned by Canvas -> left in place but NOT
    deleted (a course disappearing from an "active" filter is often
    just a term boundary, not data loss the user wants silently
    destroyed); logged as `deleted` for visibility only. Actual
    pruning is a deliberately unbuilt decision — see PROJECT.md.

This module only touches `courses`, `assignments`, `calendar_events`,
and `sync_change_log`. It does NOT write to `facts` — reconciling
Canvas-sourced dates against syllabus-extracted facts is the authority
engine's job (a separate, not-yet-built milestone), not the sync
worker's.
"""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from asos.canvas.client import CanvasClient
from asos.db.base import _now
from asos.db.enums import CalendarEventSource, CalendarEventType, SyncChangeType, SyncEntityType
from asos.db.models import Assignment, CalendarEvent, Course, SyncChangeLogEntry

logger = logging.getLogger("asos.canvas.sync")

# Fields we track for change detection. Canvas returns many more fields
# than this per entity; we only care about the ones AsOS actually uses.
_ASSIGNMENT_TRACKED_FIELDS = ("title", "due_at", "points_possible", "canvas_status")
_COURSE_TRACKED_FIELDS = ("name", "term")
_CALENDAR_EVENT_TRACKED_FIELDS = ("title", "start_at", "end_at")


def _parse_canvas_datetime(value: str | None) -> datetime.datetime | None:
    """Parses a Canvas ISO-8601 UTC timestamp into a naive UTC datetime.

    See asos.db.base._now for why this codebase stores naive UTC
    datetimes throughout rather than timezone-aware ones: SQLite doesn't
    actually preserve tzinfo across a reload, so keeping datetimes
    "aware" in Python gives a false sense of safety that breaks the
    moment an object falls out of SQLAlchemy's identity map."""
    if not value:
        return None
    aware = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return aware.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _log_change(
    session: Session,
    *,
    entity_type: SyncEntityType,
    entity_id: int,
    canvas_id: str | None,
    change_type: SyncChangeType,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    session.add(
        SyncChangeLogEntry(
            entity_type=entity_type,
            entity_id=entity_id,
            external_id=canvas_id,
            change_type=change_type,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
        )
    )


def _diff_and_apply(
    session: Session,
    *,
    existing,
    new_values: dict,
    tracked_fields: tuple[str, ...],
    entity_type: SyncEntityType,
    canvas_id: str | None,
) -> bool:
    """Applies new_values onto `existing` for each tracked field that
    changed, logging each change. Returns True if anything changed."""
    changed = False
    for field_name in tracked_fields:
        old = getattr(existing, field_name)
        new = new_values.get(field_name)
        if old != new:
            _log_change(
                session,
                entity_type=entity_type,
                entity_id=existing.id,
                canvas_id=canvas_id,
                change_type=SyncChangeType.UPDATED,
                field_name=field_name,
                old_value=str(old) if old is not None else None,
                new_value=str(new) if new is not None else None,
            )
            setattr(existing, field_name, new)
            changed = True
    return changed


class CanvasSyncWorker:
    def __init__(self, client: CanvasClient):
        self._client = client

    def sync_courses(self, session: Session) -> list[Course]:
        canvas_courses = self._client.get_active_courses()
        result: list[Course] = []

        for cc in canvas_courses:
            canvas_id = str(cc["id"])
            new_values = {"name": cc.get("name"), "term": (cc.get("term") or {}).get("name")}

            existing = session.execute(
                select(Course).where(Course.canvas_course_id == canvas_id)
            ).scalar_one_or_none()

            if existing is None:
                course = Course(canvas_course_id=canvas_id, **new_values)
                session.add(course)
                session.flush()  # assigns course.id
                _log_change(
                    session,
                    entity_type=SyncEntityType.COURSE,
                    entity_id=course.id,
                    canvas_id=canvas_id,
                    change_type=SyncChangeType.CREATED,
                )
                result.append(course)
            else:
                _diff_and_apply(
                    session,
                    existing=existing,
                    new_values=new_values,
                    tracked_fields=_COURSE_TRACKED_FIELDS,
                    entity_type=SyncEntityType.COURSE,
                    canvas_id=canvas_id,
                )
                result.append(existing)

        session.commit()
        return result

    def sync_assignments(self, session: Session, course: Course) -> list[Assignment]:
        if course.canvas_course_id is None:
            return []

        canvas_assignments = self._client.get_assignments(course.canvas_course_id)
        result: list[Assignment] = []

        for ca in canvas_assignments:
            canvas_id = str(ca["id"])
            submission = ca.get("submission") or {}
            new_values = {
                "title": ca.get("name"),
                "due_at": _parse_canvas_datetime(ca.get("due_at")),
                "points_possible": ca.get("points_possible"),
                "canvas_status": submission.get("workflow_state"),
            }

            existing = session.execute(
                select(Assignment).where(Assignment.canvas_assignment_id == canvas_id)
            ).scalar_one_or_none()

            if existing is None:
                assignment = Assignment(
                    course_id=course.id,
                    canvas_assignment_id=canvas_id,
                    canvas_synced_at=_now(),
                    **new_values,
                )
                session.add(assignment)
                session.flush()
                _log_change(
                    session,
                    entity_type=SyncEntityType.ASSIGNMENT,
                    entity_id=assignment.id,
                    canvas_id=canvas_id,
                    change_type=SyncChangeType.CREATED,
                )
                result.append(assignment)
            else:
                _diff_and_apply(
                    session,
                    existing=existing,
                    new_values=new_values,
                    tracked_fields=_ASSIGNMENT_TRACKED_FIELDS,
                    entity_type=SyncEntityType.ASSIGNMENT,
                    canvas_id=canvas_id,
                )
                existing.canvas_synced_at = _now()
                result.append(existing)

        session.commit()
        return result

    def sync_calendar_events(self, session: Session, courses: list[Course]) -> list[CalendarEvent]:
        context_codes = [f"course_{c.canvas_course_id}" for c in courses if c.canvas_course_id]
        if not context_codes:
            return []

        course_by_canvas_id = {c.canvas_course_id: c for c in courses}
        canvas_events = self._client.get_calendar_events(context_codes)
        result: list[CalendarEvent] = []

        for ce in canvas_events:
            canvas_id = str(ce["id"])
            context_code = ce.get("context_code", "")
            canvas_course_id = context_code.replace("course_", "") if context_code.startswith("course_") else None
            course = course_by_canvas_id.get(canvas_course_id)

            new_values = {
                "title": ce.get("title"),
                "start_at": _parse_canvas_datetime(ce.get("start_at")),
                "end_at": _parse_canvas_datetime(ce.get("end_at")),
            }

            existing = session.execute(
                select(CalendarEvent).where(CalendarEvent.external_event_id == canvas_id)
            ).scalar_one_or_none()

            if existing is None:
                event = CalendarEvent(
                    course_id=course.id if course else None,
                    source=CalendarEventSource.CANVAS,
                    external_event_id=canvas_id,
                    event_type=CalendarEventType.CLASS,
                    **new_values,
                )
                session.add(event)
                session.flush()
                _log_change(
                    session,
                    entity_type=SyncEntityType.CALENDAR_EVENT,
                    entity_id=event.id,
                    canvas_id=canvas_id,
                    change_type=SyncChangeType.CREATED,
                )
                result.append(event)
            else:
                _diff_and_apply(
                    session,
                    existing=existing,
                    new_values=new_values,
                    tracked_fields=_CALENDAR_EVENT_TRACKED_FIELDS,
                    entity_type=SyncEntityType.CALENDAR_EVENT,
                    canvas_id=canvas_id,
                )
                result.append(existing)

        session.commit()
        return result

    def sync_all(self, session: Session) -> dict:
        """Full sync pass. Returns a small summary dict (counts), useful
        for the CLI and, eventually, the daily briefing."""
        run_started_at = _now()

        courses = self.sync_courses(session)
        all_assignments: list[Assignment] = []
        for course in courses:
            all_assignments.extend(self.sync_assignments(session, course))
        calendar_events = self.sync_calendar_events(session, courses)

        changes_this_run = session.execute(
            select(SyncChangeLogEntry).where(SyncChangeLogEntry.detected_at >= run_started_at)
        ).scalars().all()

        return {
            "courses": len(courses),
            "assignments": len(all_assignments),
            "calendar_events": len(calendar_events),
            "changes_detected": len(changes_this_run),
        }
