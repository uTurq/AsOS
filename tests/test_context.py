from __future__ import annotations

import datetime

from asos.assessments.linking import link_concept
from asos.core.context import build_context_snapshot, format_context_for_prompt
from asos.db.enums import AssessmentType, CalendarEventType, MasteryEventType, MasteryOutcome, TaskState, TaskType
from asos.db.models import Assessment, CalendarEvent, Concept, Course, Task
from asos.mastery.events import record_mastery_event
from asos.notifications.delivery import upsert_notification_for_target
from asos.db.enums import NotificationSeverity

NOW = datetime.datetime(2026, 9, 3, 10, 0, 0)


def _course(session) -> Course:
    course = Course(name="Chemistry 1010")
    session.add(course)
    session.commit()
    return course


def test_snapshot_is_read_only(session):
    """Building a snapshot must never mutate notification delivery
    state — it's meant to be safely callable any number of times."""
    course = _course(session)
    task = Task(course_id=course.id, title="Task", task_type=TaskType.READING, state=TaskState.NOT_STARTED)
    session.add(task)
    session.commit()
    upsert_notification_for_target(
        session, severity=NotificationSeverity.NOTABLE, title="fyi", body="b", related_task_id=task.id
    )

    build_context_snapshot(session, as_of=NOW)
    build_context_snapshot(session, as_of=NOW)  # calling twice changes nothing

    from asos.db.models import Notification

    n = session.query(Notification).one()
    assert n.delivered is False


def test_todays_events_only_includes_today(session):
    course = _course(session)
    today_event = CalendarEvent(
        course_id=course.id, title="Lecture", event_type=CalendarEventType.CLASS,
        start_at=NOW.replace(hour=9), end_at=NOW.replace(hour=10),
    )
    tomorrow_event = CalendarEvent(
        course_id=course.id, title="Lab", event_type=CalendarEventType.CLASS,
        start_at=NOW + datetime.timedelta(days=1), end_at=NOW + datetime.timedelta(days=1, hours=1),
    )
    session.add_all([today_event, tomorrow_event])
    session.commit()

    snapshot = build_context_snapshot(session, as_of=NOW)
    assert [e.title for e in snapshot.todays_events] == ["Lecture"]


def test_open_tasks_excludes_done_and_skipped(session):
    course = _course(session)
    not_started = Task(course_id=course.id, title="A", task_type=TaskType.READING, state=TaskState.NOT_STARTED)
    done = Task(course_id=course.id, title="B", task_type=TaskType.READING, state=TaskState.DONE)
    skipped = Task(course_id=course.id, title="C", task_type=TaskType.READING, state=TaskState.SKIPPED)
    session.add_all([not_started, done, skipped])
    session.commit()

    snapshot = build_context_snapshot(session, as_of=NOW)
    assert [t.title for t in snapshot.open_tasks] == ["A"]


def test_upcoming_assessments_include_preparedness_when_linked(session):
    course = _course(session)
    concept = Concept(course_id=course.id, name="Buffers")
    session.add(concept)
    session.commit()
    assessment = Assessment(
        course_id=course.id, name="Exam 1", assessment_type=AssessmentType.EXAM,
        date=NOW + datetime.timedelta(days=3),
    )
    session.add(assessment)
    session.commit()
    link_concept(session, assessment_id=assessment.id, concept_id=concept.id)
    for i in range(3):
        record_mastery_event(
            session, concept_id=concept.id, event_type=MasteryEventType.QUIZ_ANSWER,
            outcome=MasteryOutcome.CORRECT, occurred_at=NOW - datetime.timedelta(days=1 + i),
        )

    snapshot = build_context_snapshot(session, as_of=NOW)
    assert len(snapshot.upcoming_assessments) == 1
    a, prep = snapshot.upcoming_assessments[0]
    assert a.name == "Exam 1"
    assert prep is not None
    assert len(prep.strong) == 1


def test_upcoming_assessment_without_links_has_none_preparedness(session):
    course = _course(session)
    assessment = Assessment(
        course_id=course.id, name="Exam 2", assessment_type=AssessmentType.EXAM,
        date=NOW + datetime.timedelta(days=5),
    )
    session.add(assessment)
    session.commit()

    snapshot = build_context_snapshot(session, as_of=NOW)
    a, prep = snapshot.upcoming_assessments[0]
    assert prep is None


def test_assessments_outside_window_excluded(session):
    course = _course(session)
    far_assessment = Assessment(
        course_id=course.id, name="Final", assessment_type=AssessmentType.FINAL,
        date=NOW + datetime.timedelta(days=90),
    )
    session.add(far_assessment)
    session.commit()

    snapshot = build_context_snapshot(session, as_of=NOW, assessment_window_days=14)
    assert snapshot.upcoming_assessments == []


def test_format_context_produces_readable_text_with_real_data(session):
    course = _course(session)
    task = Task(course_id=course.id, title="Finish worksheet", task_type=TaskType.WORKSHEET, state=TaskState.NOT_STARTED)
    session.add(task)
    session.commit()

    snapshot = build_context_snapshot(session, as_of=NOW)
    text = format_context_for_prompt(snapshot)
    assert "Finish worksheet" in text
    assert "Current time" in text
    assert "Today's schedule" in text


def test_format_context_handles_empty_state_gracefully(session):
    snapshot = build_context_snapshot(session, as_of=NOW)
    text = format_context_for_prompt(snapshot)
    assert "(nothing scheduled)" in text
    assert "(none)" in text
