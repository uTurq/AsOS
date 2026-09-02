from __future__ import annotations

import datetime

from asos.db.enums import FactConflictStatus, FactExplicitness, SourceType
from asos.db.models import Course, Fact
from asos.facts.authority import (
    find_all_conflicts,
    get_current_facts,
    record_fact,
    resolve_conflict_with_user_statement,
    resolve_fact,
    seed_default_sources,
)


def _course(session) -> Course:
    course = Course(name="Chemistry 1010")
    session.add(course)
    session.commit()
    return course


def test_seed_default_sources_is_idempotent(session):
    seed_default_sources(session)
    from asos.db.models import Source

    first_count = len(session.query(Source).all())
    seed_default_sources(session)  # calling again should not duplicate
    second_count = len(session.query(Source).all())
    assert first_count == second_count
    assert first_count == len(SourceType)


def test_single_fact_resolves_trivially(session):
    seed_default_sources(session)
    course = _course(session)

    record_fact(
        session,
        course_id=course.id,
        subject="Exam 1 date",
        value="2026-10-14",
        source_type=SourceType.SYLLABUS,
        explicitness=FactExplicitness.EXPLICIT_STATEMENT,
    )

    resolution = resolve_fact(session, course_id=course.id, subject="Exam 1 date")
    assert resolution.has_answer
    assert not resolution.has_conflict
    assert resolution.winner.value == "2026-10-14"


def test_no_facts_returns_no_answer(session):
    seed_default_sources(session)
    course = _course(session)
    resolution = resolve_fact(session, course_id=course.id, subject="Nonexistent subject")
    assert not resolution.has_answer
    assert not resolution.has_conflict


def test_clear_dominance_auto_resolves(session):
    """A recent, explicit professor announcement should outrank a
    stale, template-generated Canvas calendar entry on every axis —
    this must resolve automatically, matching the example from the
    locked design conversation."""
    seed_default_sources(session)
    course = _course(session)

    stale_time = datetime.datetime(2026, 8, 1)
    record_fact(
        session,
        course_id=course.id,
        subject="Exam 1 date",
        value="2026-10-14",
        source_type=SourceType.CANVAS_CALENDAR_AUTO,
        explicitness=FactExplicitness.DEFAULT_TEMPLATE,
        verified_at=stale_time,
    )
    fresh_time = datetime.datetime(2026, 9, 1)
    record_fact(
        session,
        course_id=course.id,
        subject="Exam 1 date",
        value="2026-10-16",
        source_type=SourceType.PROFESSOR_ANNOUNCEMENT,
        explicitness=FactExplicitness.EXPLICIT_STATEMENT,
        verified_at=fresh_time,
    )

    resolution = resolve_fact(session, course_id=course.id, subject="Exam 1 date")
    assert resolution.has_answer
    assert not resolution.has_conflict
    assert resolution.winner.value == "2026-10-16"


def test_mixed_signals_surface_as_conflict_not_silently_resolved(session):
    """The exact scenario from the design conversation: syllabus says
    one date (higher authority + more explicit, but older) and Canvas
    calendar says another (lower authority + less explicit, but more
    recently synced). Neither dominates -> must surface, not guess."""
    seed_default_sources(session)
    course = _course(session)

    older = datetime.datetime(2026, 8, 1)
    record_fact(
        session,
        course_id=course.id,
        subject="Exam 1 date",
        value="2026-10-14",
        source_type=SourceType.SYLLABUS,
        explicitness=FactExplicitness.EXPLICIT_STATEMENT,
        verified_at=older,
    )
    newer = datetime.datetime(2026, 9, 1)
    record_fact(
        session,
        course_id=course.id,
        subject="Exam 1 date",
        value="2026-10-16",
        source_type=SourceType.CANVAS_CALENDAR_AUTO,
        explicitness=FactExplicitness.DEFAULT_TEMPLATE,
        verified_at=newer,
    )

    resolution = resolve_fact(session, course_id=course.id, subject="Exam 1 date")
    assert not resolution.has_answer
    assert resolution.has_conflict
    assert {f.value for f in resolution.conflicting} == {"2026-10-14", "2026-10-16"}

    # The conflict must be persisted on the fact rows too, so other
    # code (notifications, a briefing) can query it without recomputing.
    refreshed = get_current_facts(session, course_id=course.id, subject="Exam 1 date")
    assert all(f.conflict_status == FactConflictStatus.UNRESOLVED for f in refreshed)


def test_user_resolution_supersedes_and_never_resurfaces(session):
    """Acceptance criterion 7: once the user resolves a conflict, the
    resolution is stored as a high-authority fact and does not
    resurface as a conflict again."""
    seed_default_sources(session)
    course = _course(session)

    record_fact(
        session,
        course_id=course.id,
        subject="Exam 1 date",
        value="2026-10-14",
        source_type=SourceType.SYLLABUS,
        explicitness=FactExplicitness.EXPLICIT_STATEMENT,
        verified_at=datetime.datetime(2026, 8, 1),
    )
    record_fact(
        session,
        course_id=course.id,
        subject="Exam 1 date",
        value="2026-10-16",
        source_type=SourceType.CANVAS_CALENDAR_AUTO,
        explicitness=FactExplicitness.DEFAULT_TEMPLATE,
        verified_at=datetime.datetime(2026, 9, 1),
    )
    conflicted = resolve_fact(session, course_id=course.id, subject="Exam 1 date")
    assert conflicted.has_conflict

    user_fact = resolve_conflict_with_user_statement(
        session, course_id=course.id, subject="Exam 1 date", value="2026-10-16"
    )
    assert user_fact.source.type == SourceType.USER_STATED

    resolution = resolve_fact(session, course_id=course.id, subject="Exam 1 date")
    assert resolution.has_answer
    assert not resolution.has_conflict
    assert resolution.winner.id == user_fact.id
    assert resolution.winner.value == "2026-10-16"

    # The old conflicting facts are preserved (not deleted) but marked
    # superseded/resolved, and no longer appear as current candidates.
    all_facts_ever = session.query(Fact).filter_by(subject="Exam 1 date").all()
    assert len(all_facts_ever) == 3  # 2 original + 1 user resolution, nothing deleted
    superseded = [f for f in all_facts_ever if f.id != user_fact.id]
    assert all(f.superseded_by_fact_id == user_fact.id for f in superseded)
    assert all(f.conflict_status == FactConflictStatus.RESOLVED for f in superseded)


def test_find_all_conflicts_scans_across_subjects(session):
    seed_default_sources(session)
    course = _course(session)

    # A clean, non-conflicting subject.
    record_fact(
        session,
        course_id=course.id,
        subject="Late policy",
        value="10% per day",
        source_type=SourceType.SYLLABUS,
        explicitness=FactExplicitness.EXPLICIT_STATEMENT,
    )
    # A genuinely conflicting subject.
    record_fact(
        session,
        course_id=course.id,
        subject="Exam 1 date",
        value="2026-10-14",
        source_type=SourceType.SYLLABUS,
        explicitness=FactExplicitness.EXPLICIT_STATEMENT,
        verified_at=datetime.datetime(2026, 8, 1),
    )
    record_fact(
        session,
        course_id=course.id,
        subject="Exam 1 date",
        value="2026-10-16",
        source_type=SourceType.CANVAS_CALENDAR_AUTO,
        explicitness=FactExplicitness.DEFAULT_TEMPLATE,
        verified_at=datetime.datetime(2026, 9, 1),
    )

    conflicts = find_all_conflicts(session, course_id=course.id)
    assert len(conflicts) == 1
    assert conflicts[0].subject == "Exam 1 date"


def test_unseeded_source_raises_clear_error(session):
    course = _course(session)
    import pytest

    with pytest.raises(LookupError, match="has not been seeded"):
        record_fact(
            session,
            course_id=course.id,
            subject="Exam 1 date",
            value="2026-10-14",
            source_type=SourceType.SYLLABUS,
            explicitness=FactExplicitness.EXPLICIT_STATEMENT,
        )
