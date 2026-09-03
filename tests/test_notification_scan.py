from __future__ import annotations

import datetime

from asos.assessments.linking import link_concept
from asos.db.enums import AssessmentType, MasteryEventType, MasteryOutcome, NotificationSeverity, TaskState, TaskType
from asos.db.models import Assessment, Concept, Course, Notification, Task
from asos.mastery.events import record_mastery_event
from asos.notifications.scan import scan_for_notifications

NOW = datetime.datetime(2026, 9, 1, 14, 0, 0)


def _course(session) -> Course:
    course = Course(name="Chemistry 1010")
    session.add(course)
    session.commit()
    return course


def test_scan_finds_critical_assessment_with_weak_concepts(session):
    course = _course(session)
    concept = Concept(course_id=course.id, name="Henderson-Hasselbalch equation")
    session.add(concept)
    session.commit()

    assessment = Assessment(
        course_id=course.id, name="Exam 1", assessment_type=AssessmentType.EXAM,
        date=NOW + datetime.timedelta(hours=36),
    )
    session.add(assessment)
    session.commit()
    link_concept(session, assessment_id=assessment.id, concept_id=concept.id)

    record_mastery_event(
        session, concept_id=concept.id, event_type=MasteryEventType.MISTAKE_FLAGGED,
        outcome=MasteryOutcome.INCORRECT, occurred_at=NOW - datetime.timedelta(days=2),
    )

    results = scan_for_notifications(session, as_of=NOW)
    assert len(results) == 1
    assert results[0].severity == NotificationSeverity.CRITICAL
    assert "Exam 1" in results[0].title
    assert "Henderson-Hasselbalch" in results[0].body


def test_scan_ignores_well_prepared_assessment(session):
    course = _course(session)
    concept = Concept(course_id=course.id, name="Buffers")
    session.add(concept)
    session.commit()
    assessment = Assessment(
        course_id=course.id, name="Exam 1", assessment_type=AssessmentType.EXAM,
        date=NOW + datetime.timedelta(hours=36),
    )
    session.add(assessment)
    session.commit()
    link_concept(session, assessment_id=assessment.id, concept_id=concept.id)

    for i in range(3):
        record_mastery_event(
            session, concept_id=concept.id, event_type=MasteryEventType.QUIZ_ANSWER,
            outcome=MasteryOutcome.CORRECT, occurred_at=NOW - datetime.timedelta(days=1 + i),
        )

    results = scan_for_notifications(session, as_of=NOW)
    assert results == []


def test_scan_finds_urgent_task(session):
    course = _course(session)
    task = Task(course_id=course.id, title="Finish worksheet", task_type=TaskType.WORKSHEET,
                state=TaskState.NOT_STARTED, due_at=NOW + datetime.timedelta(hours=6))
    session.add(task)
    session.commit()

    results = scan_for_notifications(session, as_of=NOW)
    assert len(results) == 1
    assert results[0].severity == NotificationSeverity.CRITICAL
    assert "Finish worksheet" in results[0].title


def test_scan_does_not_duplicate_on_repeated_calls(session):
    course = _course(session)
    task = Task(course_id=course.id, title="Finish worksheet", task_type=TaskType.WORKSHEET,
                state=TaskState.NOT_STARTED, due_at=NOW + datetime.timedelta(hours=6))
    session.add(task)
    session.commit()

    scan_for_notifications(session, as_of=NOW)
    scan_for_notifications(session, as_of=NOW)  # same conditions, called again

    all_notifications = session.query(Notification).filter_by(related_task_id=task.id).all()
    assert len(all_notifications) == 1  # not duplicated
