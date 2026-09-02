from __future__ import annotations

import datetime

from asos.db.enums import MasteryEventType, MasteryOutcome
from asos.db.models import Concept, Course
from asos.mastery.events import record_mastery_event
from asos.mastery.scoring import MasteryLevel, compute_concept_mastery

NOW = datetime.datetime(2026, 9, 1, 12, 0, 0)


def _concept(session) -> Concept:
    course = Course(name="Chemistry 1010")
    session.add(course)
    session.commit()
    concept = Concept(course_id=course.id, name="Henderson-Hasselbalch equation")
    session.add(concept)
    session.commit()
    return concept


def test_no_events_is_no_evidence_not_a_guessed_score(session):
    concept = _concept(session)
    result = compute_concept_mastery(session, concept.id, as_of=NOW)
    assert result.level == MasteryLevel.NO_EVIDENCE
    assert result.score is None
    assert result.event_count == 0


def test_all_recent_correct_is_strong(session):
    concept = _concept(session)
    for _ in range(3):
        record_mastery_event(
            session,
            concept_id=concept.id,
            event_type=MasteryEventType.QUIZ_ANSWER,
            outcome=MasteryOutcome.CORRECT,
            occurred_at=NOW - datetime.timedelta(days=1),
        )
    result = compute_concept_mastery(session, concept.id, as_of=NOW)
    assert result.level == MasteryLevel.STRONG
    assert result.score > 0.75


def test_all_recent_incorrect_is_weak(session):
    concept = _concept(session)
    for _ in range(3):
        record_mastery_event(
            session,
            concept_id=concept.id,
            event_type=MasteryEventType.QUIZ_ANSWER,
            outcome=MasteryOutcome.INCORRECT,
            occurred_at=NOW - datetime.timedelta(days=1),
        )
    result = compute_concept_mastery(session, concept.id, as_of=NOW)
    assert result.level == MasteryLevel.WEAK
    assert result.score < 0.45


def test_recent_miss_lowers_near_term_confidence_despite_good_history(session):
    """This is the core claim of event-sourced mastery: a recent miss
    should visibly move the score even if historical accuracy is high
    (acceptance criterion 12)."""
    concept = _concept(session)
    for i in range(5):
        record_mastery_event(
            session,
            concept_id=concept.id,
            event_type=MasteryEventType.QUIZ_ANSWER,
            outcome=MasteryOutcome.CORRECT,
            occurred_at=NOW - datetime.timedelta(days=7 + i),
        )
    baseline = compute_concept_mastery(session, concept.id, as_of=NOW)
    assert baseline.level == MasteryLevel.STRONG

    record_mastery_event(
        session,
        concept_id=concept.id,
        event_type=MasteryEventType.MISTAKE_FLAGGED,
        outcome=MasteryOutcome.INCORRECT,
        occurred_at=NOW - datetime.timedelta(days=1),
    )
    after_miss = compute_concept_mastery(session, concept.id, as_of=NOW)
    assert after_miss.score < baseline.score
    assert after_miss.level in (MasteryLevel.DEVELOPING, MasteryLevel.WEAK)


def test_stale_evidence_without_recent_review_is_not_confidently_strong(session):
    """Even a perfect track record shouldn't register as confidently
    'strong' if it's all old and hasn't been reviewed since — the
    system should reflect "we're not sure anymore," not "still great."""
    concept = _concept(session)
    for i in range(5):
        record_mastery_event(
            session,
            concept_id=concept.id,
            event_type=MasteryEventType.QUIZ_ANSWER,
            outcome=MasteryOutcome.CORRECT,
            occurred_at=NOW - datetime.timedelta(days=60 + i),
        )
    result = compute_concept_mastery(session, concept.id, as_of=NOW)
    assert result.level != MasteryLevel.STRONG


def test_single_old_event_shrinks_more_than_many_recent_events(session):
    """Confidence should increase with more evidence — a single old
    correct answer says much less than five recent correct answers."""
    course = Course(name="Biology 101")
    session.add(course)
    session.commit()

    sparse_concept = Concept(course_id=course.id, name="Sparse concept")
    rich_concept = Concept(course_id=course.id, name="Well-reviewed concept")
    session.add_all([sparse_concept, rich_concept])
    session.commit()

    record_mastery_event(
        session,
        concept_id=sparse_concept.id,
        event_type=MasteryEventType.QUIZ_ANSWER,
        outcome=MasteryOutcome.CORRECT,
        occurred_at=NOW - datetime.timedelta(days=45),
    )
    for i in range(5):
        record_mastery_event(
            session,
            concept_id=rich_concept.id,
            event_type=MasteryEventType.QUIZ_ANSWER,
            outcome=MasteryOutcome.CORRECT,
            occurred_at=NOW - datetime.timedelta(days=1 + i),
        )

    sparse_result = compute_concept_mastery(session, sparse_concept.id, as_of=NOW)
    rich_result = compute_concept_mastery(session, rich_concept.id, as_of=NOW)

    assert sparse_result.score < rich_result.score
    assert rich_result.level == MasteryLevel.STRONG


def test_last_reviewed_reflects_most_recent_event(session):
    concept = _concept(session)
    record_mastery_event(
        session, concept_id=concept.id, event_type=MasteryEventType.STUDY_SESSION,
        outcome=MasteryOutcome.PARTIAL, occurred_at=NOW - datetime.timedelta(days=10),
    )
    record_mastery_event(
        session, concept_id=concept.id, event_type=MasteryEventType.QUIZ_ANSWER,
        outcome=MasteryOutcome.CORRECT, occurred_at=NOW - datetime.timedelta(days=2),
    )
    result = compute_concept_mastery(session, concept.id, as_of=NOW)
    assert result.last_reviewed == NOW - datetime.timedelta(days=2)
    assert result.event_count == 2


def test_events_are_exposed_for_explainability(session):
    """Acceptance criterion 9: 'why am I weak on X' must surface actual
    mastery events, not just a restated score."""
    concept = _concept(session)
    record_mastery_event(
        session, concept_id=concept.id, event_type=MasteryEventType.MISTAKE_FLAGGED,
        outcome=MasteryOutcome.INCORRECT, occurred_at=NOW - datetime.timedelta(days=9),
        notes="mixed up numerator and denominator",
    )
    result = compute_concept_mastery(session, concept.id, as_of=NOW)
    assert result.level == MasteryLevel.WEAK
    assert len(result.events) == 1
    assert result.events[0].notes == "mixed up numerator and denominator"


def test_self_rated_outcome_requires_self_rating(session):
    concept = _concept(session)
    import pytest

    with pytest.raises(ValueError, match="self_rating"):
        record_mastery_event(
            session, concept_id=concept.id, event_type=MasteryEventType.SELF_REPORT,
            outcome=MasteryOutcome.SELF_RATED,
        )


def test_self_rated_maps_rating_to_score(session):
    concept = _concept(session)
    event = record_mastery_event(
        session, concept_id=concept.id, event_type=MasteryEventType.SELF_REPORT,
        outcome=MasteryOutcome.SELF_RATED, self_rating=5,
    )
    assert event.outcome_score == 1.0

    event2 = record_mastery_event(
        session, concept_id=concept.id, event_type=MasteryEventType.SELF_REPORT,
        outcome=MasteryOutcome.SELF_RATED, self_rating=1,
    )
    assert event2.outcome_score == 0.0


def test_explicit_outcome_score_overrides_default(session):
    concept = _concept(session)
    event = record_mastery_event(
        session, concept_id=concept.id, event_type=MasteryEventType.QUIZ_ANSWER,
        outcome=MasteryOutcome.PARTIAL, outcome_score=0.8,
    )
    assert event.outcome_score == 0.8
