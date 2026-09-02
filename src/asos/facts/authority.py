"""
Fact authority and conflict resolution.

Core design decision (locked in PROJECT.md): Canvas is NOT universally
authoritative. Authority is a function of three independent axes:

  1. source type's base authority weight (e.g. a professor's explicit
     announcement outranks an auto-generated Canvas calendar entry)
  2. explicitness (an explicit statement outranks something inferred
     or a generic template default)
  3. recency (verified_at — a newer statement outranks a stale one)

A fact only ever wins automatically over a competing fact about the
same subject if it is at least as strong on ALL THREE axes (a genuine
dominance) — never on a single blended score, which would hide *why*
something won and could silently pick a fact that's only "better on
average" while actually being staler or less explicit than the
alternative. When no fact dominates all competitors, the conflict is
surfaced, not guessed at — this is the direct implementation of the
locked requirement that Canvas-vs-syllabus (or any other source pair)
disagreements must be visible to the user, not silently resolved.

Facts are never deleted or edited to "fix" a conflict. Resolving one
via a user statement (see `resolve_conflict_with_user_statement`)
creates a NEW fact and marks the previous ones as superseded — the
full history stays queryable.
"""

from __future__ import annotations

import dataclasses

from sqlalchemy import select
from sqlalchemy.orm import Session

from asos.db.base import _now
from asos.db.enums import FactConfidence, FactConflictStatus, FactExplicitness, SourceType
from asos.db.models import Fact, Source

# Default base authority weights per source type. Deliberately a plain
# dict (not hardcoded per-fact) so it's the one place these numbers
# live — seeded into the `sources` table on startup/init, never
# hardcoded again elsewhere. Higher = more authoritative by default.
DEFAULT_SOURCE_AUTHORITY_WEIGHTS: dict[SourceType, int] = {
    SourceType.USER_STATED: 95,
    SourceType.PROFESSOR_ANNOUNCEMENT: 90,
    SourceType.SYLLABUS: 70,
    SourceType.LECTURE_RECORDING: 60,
    SourceType.CANVAS_API: 50,
    SourceType.CANVAS_CALENDAR_AUTO: 35,
    SourceType.CLAUDE_INFERRED: 20,
}

_EXPLICITNESS_RANK: dict[FactExplicitness, int] = {
    FactExplicitness.DEFAULT_TEMPLATE: 0,
    FactExplicitness.INFERRED: 1,
    FactExplicitness.EXPLICIT_STATEMENT: 2,
}

_EXPLICITNESS_DEFAULT_CONFIDENCE: dict[FactExplicitness, FactConfidence] = {
    FactExplicitness.EXPLICIT_STATEMENT: FactConfidence.HIGH,
    FactExplicitness.INFERRED: FactConfidence.MEDIUM,
    FactExplicitness.DEFAULT_TEMPLATE: FactConfidence.LOW,
}


def seed_default_sources(session: Session) -> None:
    """Idempotently ensures every SourceType has a `sources` row with a
    default authority weight. Safe to call on every startup — does
    nothing if all source types are already present."""
    existing_types = {s.type for s in session.execute(select(Source)).scalars().all()}
    added = False
    for source_type, weight in DEFAULT_SOURCE_AUTHORITY_WEIGHTS.items():
        if source_type not in existing_types:
            session.add(Source(type=source_type, base_authority_weight=weight))
            added = True
    if added:
        session.commit()


def get_source(session: Session, source_type: SourceType) -> Source:
    source = session.execute(select(Source).where(Source.type == source_type)).scalar_one_or_none()
    if source is None:
        raise LookupError(
            f"Source type {source_type} has not been seeded into the sources table — "
            "call seed_default_sources() first."
        )
    return source


def record_fact(
    session: Session,
    *,
    course_id: int | None,
    subject: str,
    value: str,
    source_type: SourceType,
    explicitness: FactExplicitness,
    confidence: FactConfidence | None = None,
    document_id: int | None = None,
    verified_at=None,
) -> Fact:
    """Records a new fact. Never touches or supersedes any existing fact
    about the same subject — that's resolve_fact's job at query time, and
    resolve_conflict_with_user_statement's job when the user explicitly
    settles a conflict."""
    source = get_source(session, source_type)
    fact = Fact(
        course_id=course_id,
        subject=subject,
        value=value,
        source_id=source.id,
        document_id=document_id,
        explicitness=explicitness,
        confidence=confidence or _EXPLICITNESS_DEFAULT_CONFIDENCE[explicitness],
        verified_at=verified_at or _now(),
    )
    session.add(fact)
    session.commit()
    return fact


def get_current_facts(session: Session, *, course_id: int | None, subject: str) -> list[Fact]:
    """All non-superseded facts for a subject — the candidate set
    resolve_fact chooses between."""
    stmt = select(Fact).where(Fact.subject == subject, Fact.superseded_by_fact_id.is_(None))
    if course_id is not None:
        stmt = stmt.where(Fact.course_id == course_id)
    return list(session.execute(stmt).scalars().all())


def _authority_tuple(fact: Fact) -> tuple[int, int, object]:
    return (fact.source.base_authority_weight, _EXPLICITNESS_RANK[fact.explicitness], fact.verified_at)


def _dominates(a: Fact, b: Fact) -> bool:
    """True if `a` is at least as strong as `b` on every axis, and
    strictly stronger on at least one — a genuine dominance, not a tie."""
    a_tuple, b_tuple = _authority_tuple(a), _authority_tuple(b)
    at_least_as_strong = all(x >= y for x, y in zip(a_tuple, b_tuple))
    strictly_stronger_somewhere = a_tuple != b_tuple
    return at_least_as_strong and strictly_stronger_somewhere


@dataclasses.dataclass
class FactResolution:
    subject: str
    course_id: int | None
    winner: Fact | None
    conflicting: list[Fact]
    all_candidates: list[Fact]

    @property
    def has_conflict(self) -> bool:
        return len(self.conflicting) > 0

    @property
    def has_answer(self) -> bool:
        return self.winner is not None


def resolve_fact(session: Session, *, course_id: int | None, subject: str) -> FactResolution:
    """Resolves the current best answer for a subject, if there is one.

    Also persists the conflict_status annotation on the underlying
    Fact rows (UNRESOLVED when genuinely conflicting, NONE otherwise)
    so other code (notifications, a future dashboard) can query "what's
    currently unresolved" without recomputing this. This is bookkeeping
    on the annotation field only — a fact's subject/value/source/
    verified_at are never touched here.
    """
    candidates = get_current_facts(session, course_id=course_id, subject=subject)

    if not candidates:
        return FactResolution(subject=subject, course_id=course_id, winner=None, conflicting=[], all_candidates=[])

    if len(candidates) == 1:
        candidates[0].conflict_status = FactConflictStatus.NONE
        session.commit()
        return FactResolution(
            subject=subject, course_id=course_id, winner=candidates[0], conflicting=[], all_candidates=candidates
        )

    dominant = None
    for candidate in candidates:
        if all(candidate is other or _dominates(candidate, other) for other in candidates):
            dominant = candidate
            break

    if dominant is not None:
        for c in candidates:
            c.conflict_status = FactConflictStatus.NONE
        session.commit()
        return FactResolution(
            subject=subject, course_id=course_id, winner=dominant, conflicting=[], all_candidates=candidates
        )

    for c in candidates:
        c.conflict_status = FactConflictStatus.UNRESOLVED
    session.commit()
    return FactResolution(
        subject=subject, course_id=course_id, winner=None, conflicting=candidates, all_candidates=candidates
    )


def find_all_conflicts(session: Session, *, course_id: int | None = None) -> list[FactResolution]:
    """Scans every (course_id, subject) pair with more than one current
    fact and returns the resolutions that are genuine unresolved
    conflicts. This is what a daily briefing / notification pass would
    call to decide what to surface."""
    stmt = select(Fact.course_id, Fact.subject).where(Fact.superseded_by_fact_id.is_(None)).distinct()
    if course_id is not None:
        stmt = stmt.where(Fact.course_id == course_id)

    conflicts = []
    for row_course_id, subject in session.execute(stmt).all():
        resolution = resolve_fact(session, course_id=row_course_id, subject=subject)
        if resolution.has_conflict:
            conflicts.append(resolution)
    return conflicts


def resolve_conflict_with_user_statement(
    session: Session, *, course_id: int | None, subject: str, value: str
) -> Fact:
    """The user has explicitly settled a conflict (e.g. via voice/text:
    "the exam is definitely on the 16th"). Records their answer as a
    new, high-authority fact and marks every currently-current fact for
    this subject as superseded by it. Superseded facts are never
    deleted — they just stop being candidates in future resolutions, so
    the resolved conflict never resurfaces (locked acceptance
    criterion 7)."""
    new_fact = record_fact(
        session,
        course_id=course_id,
        subject=subject,
        value=value,
        source_type=SourceType.USER_STATED,
        explicitness=FactExplicitness.EXPLICIT_STATEMENT,
        confidence=FactConfidence.HIGH,
    )

    previous_facts = [
        f
        for f in get_current_facts(session, course_id=course_id, subject=subject)
        if f.id != new_fact.id
    ]
    for f in previous_facts:
        f.superseded_by_fact_id = new_fact.id
        f.conflict_status = FactConflictStatus.RESOLVED
    session.commit()

    return new_fact
