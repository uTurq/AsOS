from __future__ import annotations

import datetime

import pytest
from icalendar import Calendar, Event

from asos.calendar_feed.parsing import parse_ics
from asos.calendar_feed.sync import ICSFetchError, fetch_ics, sync_ics_text
from asos.db.enums import CalendarEventSource, SyncChangeType
from asos.db.models import CalendarEvent, SyncChangeLogEntry


def _build_ics(events: list[dict]) -> str:
    """Builds real ICS text using the icalendar library itself, mirroring
    how the PDF/DOCX/PPTX parser tests build real fixture files rather
    than hand-writing raw format strings."""
    cal = Calendar()
    cal.add("prodid", "-//Test//Test//EN")
    cal.add("version", "2.0")
    for e in events:
        ev = Event()
        ev.add("uid", e["uid"])
        ev.add("summary", e["summary"])
        ev.add("dtstart", e["dtstart"])
        if "dtend" in e:
            ev.add("dtend", e["dtend"])
        if "description" in e:
            ev.add("description", e["description"])
        cal.add_component(ev)
    return cal.to_ical().decode("utf-8")


def test_parse_ics_basic_event():
    ics_text = _build_ics(
        [
            {
                "uid": "event-1@canvas",
                "summary": "Exam 1",
                "dtstart": datetime.datetime(2026, 10, 14, 14, 0, tzinfo=datetime.timezone.utc),
                "dtend": datetime.datetime(2026, 10, 14, 15, 0, tzinfo=datetime.timezone.utc),
                "description": "Covers chapters 1-4",
            }
        ]
    )
    events = parse_ics(ics_text)
    assert len(events) == 1
    e = events[0]
    assert e.uid == "event-1@canvas"
    assert e.title == "Exam 1"
    assert e.start_at == datetime.datetime(2026, 10, 14, 14, 0)  # naive UTC
    assert e.end_at == datetime.datetime(2026, 10, 14, 15, 0)
    assert "chapters 1-4" in e.description


def test_parse_ics_converts_timezone_aware_to_naive_utc():
    import zoneinfo

    eastern = zoneinfo.ZoneInfo("America/New_York")
    ics_text = _build_ics(
        [{"uid": "e2", "summary": "Class", "dtstart": datetime.datetime(2026, 9, 1, 10, 0, tzinfo=eastern)}]
    )
    events = parse_ics(ics_text)
    assert events[0].start_at == datetime.datetime(2026, 9, 1, 14, 0)  # 10am EDT (UTC-4 in September) -> 2pm UTC
    assert events[0].start_at.tzinfo is None


def test_parse_ics_all_day_event_becomes_midnight():
    ics_text = _build_ics([{"uid": "e3", "summary": "Assignment due", "dtstart": datetime.date(2026, 10, 20)}])
    events = parse_ics(ics_text)
    assert events[0].start_at == datetime.datetime(2026, 10, 20, 0, 0)


def test_parse_ics_multiple_events():
    ics_text = _build_ics(
        [
            {"uid": "e1", "summary": "Lecture 1", "dtstart": datetime.datetime(2026, 9, 1, 9, 0)},
            {"uid": "e2", "summary": "Lecture 2", "dtstart": datetime.datetime(2026, 9, 3, 9, 0)},
        ]
    )
    events = parse_ics(ics_text)
    assert len(events) == 2
    assert {e.title for e in events} == {"Lecture 1", "Lecture 2"}


def test_parse_ics_empty_calendar_returns_no_events():
    ics_text = _build_ics([])
    assert parse_ics(ics_text) == []


class _FakeHttpResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class _FakeHttpSession:
    def __init__(self, response: _FakeHttpResponse):
        self._response = response

    def get(self, url, timeout=15.0):
        return self._response


def test_fetch_ics_returns_body_text():
    ics_text = _build_ics([{"uid": "e1", "summary": "Test", "dtstart": datetime.datetime(2026, 1, 1, 9, 0)}])
    session = _FakeHttpSession(_FakeHttpResponse(ics_text))
    result = fetch_ics("https://school.instructure.com/feeds/calendars/abc123.ics", session=session)
    assert "Test" in result


def test_fetch_ics_non_200_raises_clear_error():
    session = _FakeHttpSession(_FakeHttpResponse("", status_code=404))
    with pytest.raises(ICSFetchError, match="404"):
        fetch_ics("https://example.com/feed.ics", session=session)


def test_sync_creates_new_events(session):
    ics_text = _build_ics(
        [{"uid": "ev-1", "summary": "Exam 1", "dtstart": datetime.datetime(2026, 10, 14, 14, 0)}]
    )
    summary = sync_ics_text(session, ics_text)
    assert summary == {"events_seen": 1, "created": 1, "changes_detected": 1}

    event = session.query(CalendarEvent).one()
    assert event.title == "Exam 1"
    assert event.source == CalendarEventSource.ICS_FEED
    assert event.external_event_id == "ev-1"


def test_sync_is_idempotent_on_unchanged_feed(session):
    ics_text = _build_ics(
        [{"uid": "ev-1", "summary": "Exam 1", "dtstart": datetime.datetime(2026, 10, 14, 14, 0)}]
    )
    sync_ics_text(session, ics_text)
    summary = sync_ics_text(session, ics_text)  # re-sync identical feed
    assert summary["changes_detected"] == 0
    assert session.query(CalendarEvent).count() == 1  # not duplicated


def test_sync_detects_and_logs_a_changed_field(session):
    ics_v1 = _build_ics([{"uid": "ev-1", "summary": "Exam 1", "dtstart": datetime.datetime(2026, 10, 14, 14, 0)}])
    sync_ics_text(session, ics_v1)

    ics_v2 = _build_ics([{"uid": "ev-1", "summary": "Exam 1", "dtstart": datetime.datetime(2026, 10, 16, 14, 0)}])
    summary = sync_ics_text(session, ics_v2)
    assert summary["changes_detected"] == 1

    event = session.query(CalendarEvent).one()
    assert event.start_at == datetime.datetime(2026, 10, 16, 14, 0)

    diff = session.query(SyncChangeLogEntry).filter_by(field_name="start_at").one()
    assert diff.change_type == SyncChangeType.UPDATED
    assert "2026-10-14" in diff.old_value
    assert "2026-10-16" in diff.new_value


def test_sync_associates_events_with_given_course(session):
    from asos.db.models import Course

    course = Course(name="Chemistry 1010")
    session.add(course)
    session.commit()

    ics_text = _build_ics([{"uid": "ev-1", "summary": "Exam 1", "dtstart": datetime.datetime(2026, 10, 14, 14, 0)}])
    sync_ics_text(session, ics_text, course_id=course.id)

    event = session.query(CalendarEvent).one()
    assert event.course_id == course.id
