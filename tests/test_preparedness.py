from __future__ import annotations

import datetime

from asos.assessments.linking import link_concept, link_document
from asos.assessments.preparedness import compute_assessment_preparedness
from asos.db.enums import AssessmentType, DocumentSourceType, MasteryEventType, MasteryOutcome
from asos.db.models import Assessment, Concept, Course, Document
from asos.mastery.events import record_mastery_event

NOW = datetime.datetime(2026, 9, 1, 12, 0, 0)


def _setup_course(session):
    course = Course(name="Chemistry 1010")
    session.add(course)
    session.commit()
    return course


def test_link_concept_is_idempotent_and_updates_importance(session):
    course = _setup_course(session)
    concept = Concept(course_id=course.id, name="Buffers")
    assessment = Assessment(course_id=course.id, name="Exam 1", assessment_type=AssessmentType.EXAM)
    session.add_all([concept, assessment])
    session.commit()

    link_concept(session, assessment_id=assessment.id, concept_id=concept.id, importance=3)
    link_concept(session, assessment_id=assessment.id, concept_id=concept.id, importance=5)

    from asos.db.models import AssessmentConcept

    links = session.query(AssessmentConcept).filter_by(assessment_id=assessment.id, concept_id=concept.id).all()
    assert len(links) == 1  # not duplicated
    assert links[0].importance == 5  # updated, not stuck at the first value


def test_link_document_is_idempotent(session):
    course = _setup_course(session)
    assessment = Assessment(course_id=course.id, name="Exam 1", assessment_type=AssessmentType.EXAM)
    document = Document(course_id=course.id, title="Study Guide", source_type=DocumentSourceType.STUDY_GUIDE, file_path="/fake")
    session.add_all([assessment, document])
    session.commit()

    link_document(session, assessment_id=assessment.id, document_id=document.id)
    link_document(session, assessment_id=assessment.id, document_id=document.id)

    from asos.db.models import AssessmentDocument

    links = session.query(AssessmentDocument).filter_by(assessment_id=assessment.id, document_id=document.id).all()
    assert len(links) == 1


def test_preparedness_breakdown_matches_worked_example_from_design(session):
    """Reproduces the exact worked example from the original design
    conversation: 'Strong: buffers, titration curves. Weak:
    Henderson-Hasselbalch (2 recent misses). No evidence yet:
    acid-base titration edge cases (never studied).'"""
    course = _setup_course(session)
    buffers = Concept(course_id=course.id, name="Buffers")
    titration_curves = Concept(course_id=course.id, name="Titration curves")
    henderson = Concept(course_id=course.id, name="Henderson-Hasselbalch equation")
    edge_cases = Concept(course_id=course.id, name="Acid-base titration edge cases")
    session.add_all([buffers, titration_curves, henderson, edge_cases])
    session.commit()

    assessment = Assessment(course_id=course.id, name="Exam 1", assessment_type=AssessmentType.EXAM)
    session.add(assessment)
    session.commit()

    for concept in (buffers, titration_curves, henderson, edge_cases):
        link_concept(session, assessment_id=assessment.id, concept_id=concept.id)

    for concept in (buffers, titration_curves):
        for i in range(3):
            record_mastery_event(
                session, concept_id=concept.id, event_type=MasteryEventType.QUIZ_ANSWER,
                outcome=MasteryOutcome.CORRECT, occurred_at=NOW - datetime.timedelta(days=2 + i),
            )

    for _ in range(2):
        record_mastery_event(
            session, concept_id=henderson.id, event_type=MasteryEventType.MISTAKE_FLAGGED,
            outcome=MasteryOutcome.INCORRECT, occurred_at=NOW - datetime.timedelta(days=9),
        )
    # edge_cases: never studied — no events at all.

    prep = compute_assessment_preparedness(session, assessment.id, as_of=NOW)

    assert {c.concept.name for c in prep.strong} == {"Buffers", "Titration curves"}
    assert {c.concept.name for c in prep.weak} == {"Henderson-Hasselbalch equation"}
    assert {c.concept.name for c in prep.no_evidence} == {"Acid-base titration edge cases"}
    assert prep.developing == []


def test_overall_score_excludes_no_evidence_concepts(session):
    course = _setup_course(session)
    studied = Concept(course_id=course.id, name="Studied concept")
    unstudied = Concept(course_id=course.id, name="Unstudied concept")
    session.add_all([studied, unstudied])
    session.commit()

    assessment = Assessment(course_id=course.id, name="Exam 1", assessment_type=AssessmentType.EXAM)
    session.add(assessment)
    session.commit()
    link_concept(session, assessment_id=assessment.id, concept_id=studied.id)
    link_concept(session, assessment_id=assessment.id, concept_id=unstudied.id)

    for i in range(3):
        record_mastery_event(
            session, concept_id=studied.id, event_type=MasteryEventType.QUIZ_ANSWER,
            outcome=MasteryOutcome.CORRECT, occurred_at=NOW - datetime.timedelta(days=1 + i),
        )

    prep = compute_assessment_preparedness(session, assessment.id, as_of=NOW)
    # The unstudied concept must NOT drag the score toward 0 — it's
    # simply excluded, not treated as a failing grade.
    assert prep.overall_score > 0.75


def test_overall_score_none_when_nothing_has_evidence(session):
    course = _setup_course(session)
    concept = Concept(course_id=course.id, name="Never studied")
    session.add(concept)
    session.commit()
    assessment = Assessment(course_id=course.id, name="Exam 1", assessment_type=AssessmentType.EXAM)
    session.add(assessment)
    session.commit()
    link_concept(session, assessment_id=assessment.id, concept_id=concept.id)

    prep = compute_assessment_preparedness(session, assessment.id, as_of=NOW)
    assert prep.overall_score is None  # never fabricated as 0.0


def test_coverage_reflects_studied_fraction_by_importance(session):
    course = _setup_course(session)
    studied = Concept(course_id=course.id, name="Studied")
    unstudied = Concept(course_id=course.id, name="Unstudied")
    session.add_all([studied, unstudied])
    session.commit()
    assessment = Assessment(course_id=course.id, name="Exam 1", assessment_type=AssessmentType.EXAM)
    session.add(assessment)
    session.commit()

    link_concept(session, assessment_id=assessment.id, concept_id=studied.id, importance=1)
    link_concept(session, assessment_id=assessment.id, concept_id=unstudied.id, importance=1)
    record_mastery_event(
        session, concept_id=studied.id, event_type=MasteryEventType.QUIZ_ANSWER,
        outcome=MasteryOutcome.CORRECT, occurred_at=NOW - datetime.timedelta(days=1),
    )

    prep = compute_assessment_preparedness(session, assessment.id, as_of=NOW)
    assert prep.coverage == 0.5  # equal importance, half studied


def test_unknown_assessment_raises_clear_error(session):
    import pytest

    with pytest.raises(LookupError):
        compute_assessment_preparedness(session, 99999)
