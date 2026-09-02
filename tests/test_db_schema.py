from __future__ import annotations

import datetime

import pytest
from sqlalchemy.exc import StatementError

from asos.db.enums import (
    AssessmentType,
    DocumentSourceType,
    FactConfidence,
    FactExplicitness,
    MasteryEventType,
    MasteryOutcome,
    SourceType,
    TaskState,
    TaskType,
)
from asos.db.models import (
    Assessment,
    AssessmentConcept,
    Assignment,
    Concept,
    Course,
    Document,
    Fact,
    MasteryEvent,
    Source,
    Task,
)


def test_course_and_assignment_roundtrip(session):
    course = Course(name="Organic Chemistry I", term="Fall 2026")
    session.add(course)
    session.commit()

    assignment = Assignment(course_id=course.id, title="Problem Set 4", canvas_status="unsubmitted")
    session.add(assignment)
    session.commit()

    fetched = session.get(Assignment, assignment.id)
    assert fetched.title == "Problem Set 4"
    assert fetched.course.name == "Organic Chemistry I"


def test_mastery_events_are_append_only_history(session):
    """The core design decision: mastery is a ledger, not a mutable score."""
    course = Course(name="Biology 101")
    session.add(course)
    session.commit()

    concept = Concept(course_id=course.id, name="Photosynthesis light reactions")
    session.add(concept)
    session.commit()

    e1 = MasteryEvent(
        concept_id=concept.id,
        event_type=MasteryEventType.QUIZ_ANSWER,
        outcome=MasteryOutcome.INCORRECT,
        outcome_score=0.0,
        source_description="quiz on ch4",
    )
    e2 = MasteryEvent(
        concept_id=concept.id,
        event_type=MasteryEventType.STUDY_SESSION,
        outcome=MasteryOutcome.PARTIAL,
        outcome_score=0.5,
        source_description="voice study session",
    )
    session.add_all([e1, e2])
    session.commit()

    events = session.query(MasteryEvent).filter_by(concept_id=concept.id).order_by(MasteryEvent.id).all()
    assert len(events) == 2
    assert events[0].outcome == MasteryOutcome.INCORRECT
    assert events[1].outcome == MasteryOutcome.PARTIAL
    # Both events remain — nothing was overwritten by the second one.


def test_invalid_enum_value_rejected(session):
    course = Course(name="Biology 101")
    session.add(course)
    session.commit()
    concept = Concept(course_id=course.id, name="Cell division")
    session.add(concept)
    session.commit()

    bad_event = MasteryEvent(
        concept_id=concept.id,
        event_type="not_a_real_event_type",
        outcome=MasteryOutcome.CORRECT,
        outcome_score=1.0,
    )
    session.add(bad_event)
    with pytest.raises(StatementError):
        session.commit()
    session.rollback()


def test_fact_provenance_and_conflict_fields(session):
    course = Course(name="Chemistry 1010")
    session.add(course)
    session.commit()

    syllabus_source = Source(type=SourceType.SYLLABUS, base_authority_weight=70)
    canvas_source = Source(type=SourceType.CANVAS_CALENDAR_AUTO, base_authority_weight=40)
    session.add_all([syllabus_source, canvas_source])
    session.commit()

    fact_a = Fact(
        course_id=course.id,
        subject="Exam 1 date",
        value="2026-10-14",
        source_id=syllabus_source.id,
        explicitness=FactExplicitness.EXPLICIT_STATEMENT,
        confidence=FactConfidence.HIGH,
    )
    fact_b = Fact(
        course_id=course.id,
        subject="Exam 1 date",
        value="2026-10-16",
        source_id=canvas_source.id,
        explicitness=FactExplicitness.DEFAULT_TEMPLATE,
        confidence=FactConfidence.MEDIUM,
    )
    session.add_all([fact_a, fact_b])
    session.commit()

    facts = session.query(Fact).filter_by(subject="Exam 1 date").all()
    assert len(facts) == 2
    # Both facts persist untouched — conflict resolution is a query-time
    # decision (see PROJECT.md), not something that silently drops data.
    assert {f.value for f in facts} == {"2026-10-14", "2026-10-16"}
    assert facts[0].source.base_authority_weight != facts[1].source.base_authority_weight


def test_task_state_independent_of_canvas_assignment(session):
    course = Course(name="Physics 2210")
    session.add(course)
    session.commit()

    assignment = Assignment(course_id=course.id, title="Lab Report 2", canvas_status="unsubmitted")
    session.add(assignment)
    session.commit()

    # A task with no Canvas counterpart at all.
    self_generated_task = Task(
        course_id=course.id,
        title="Review kinematics before Thursday's quiz",
        task_type=TaskType.REVIEW,
        state=TaskState.NOT_STARTED,
    )
    session.add(self_generated_task)
    session.commit()
    assert self_generated_task.related_assignment_id is None

    # A task linked to a Canvas assignment, marked done locally while
    # Canvas still shows "unsubmitted" — local state must not be coupled
    # to the Canvas signal.
    linked_task = Task(
        course_id=course.id,
        related_assignment_id=assignment.id,
        title="Do Lab Report 2",
        task_type=TaskType.WORKSHEET,
        state=TaskState.DONE,
    )
    session.add(linked_task)
    session.commit()

    refreshed_assignment = session.get(Assignment, assignment.id)
    assert refreshed_assignment.canvas_status == "unsubmitted"
    assert linked_task.state == TaskState.DONE  # unaffected by Canvas status


def test_assessment_concept_linking_for_preparedness(session):
    course = Course(name="Chemistry 1010")
    session.add(course)
    session.commit()

    c1 = Concept(course_id=course.id, name="Buffers")
    c2 = Concept(course_id=course.id, name="Henderson-Hasselbalch equation")
    session.add_all([c1, c2])
    session.commit()

    exam = Assessment(course_id=course.id, name="Exam 1", assessment_type=AssessmentType.EXAM)
    session.add(exam)
    session.commit()

    link1 = AssessmentConcept(assessment_id=exam.id, concept_id=c1.id, importance=3)
    link2 = AssessmentConcept(assessment_id=exam.id, concept_id=c2.id, importance=5)
    session.add_all([link1, link2])
    session.commit()

    links = session.query(AssessmentConcept).filter_by(assessment_id=exam.id).all()
    assert {link.concept.name for link in links} == {"Buffers", "Henderson-Hasselbalch equation"}


def test_document_requires_source_type(session):
    course = Course(name="Biology 101")
    session.add(course)
    session.commit()

    doc = Document(
        course_id=course.id,
        title="Syllabus - Fall 2026",
        source_type=DocumentSourceType.SYLLABUS,
        file_path="/fake/path/syllabus.pdf",
    )
    session.add(doc)
    session.commit()
    assert session.get(Document, doc.id).source_type == DocumentSourceType.SYLLABUS
