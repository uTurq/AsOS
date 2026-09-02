"""
Derived mastery scoring.

There is no stored mastery score anywhere in the schema — this module
computes one fresh, every time, from the append-only mastery_events
ledger. That's the whole point of the event-sourced design: "why does
it think that?" is always answerable by looking at the actual events
a score came from (see ConceptMasteryResult.events below).

Scoring model, in plain terms:
  - Each event contributes outcome_score (0.0-1.0), weighted by how
    recent it is (exponential decay, HALF_LIFE_DAYS).
  - The weighted average is shrunk toward a neutral prior (0.5) by an
    amount inversely proportional to total evidence weight — a single
    old event says much less than five recent ones, so it shrinks
    harder toward "we're not sure." This is standard Bayesian-average
    smoothing (a "prior pseudo-count"), not anything exotic.
  - A concept with zero events is NOT given a score of 0.0 or 0.5 —
    it's a distinct NO_EVIDENCE state, because "never studied" and
    "studied and struggling" are different facts and conflating them
    would misrepresent what AsOS actually knows.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from asos.db.base import _now
from asos.db.models import MasteryEvent

HALF_LIFE_DAYS = 14.0
PRIOR_WEIGHT = 1.0
PRIOR_SCORE = 0.5

STRONG_THRESHOLD = 0.75
WEAK_THRESHOLD = 0.45


class MasteryLevel(str, enum.Enum):
    NO_EVIDENCE = "no_evidence"
    WEAK = "weak"
    DEVELOPING = "developing"
    STRONG = "strong"


@dataclasses.dataclass
class ConceptMasteryResult:
    concept_id: int
    level: MasteryLevel
    score: float | None  # None only when level is NO_EVIDENCE
    event_count: int
    last_reviewed: datetime.datetime | None
    events: list[MasteryEvent]  # raw evidence, oldest first — the "why"


def _categorize(score: float) -> MasteryLevel:
    if score >= STRONG_THRESHOLD:
        return MasteryLevel.STRONG
    if score < WEAK_THRESHOLD:
        return MasteryLevel.WEAK
    return MasteryLevel.DEVELOPING


def compute_concept_mastery(
    session: Session, concept_id: int, *, as_of: datetime.datetime | None = None
) -> ConceptMasteryResult:
    as_of = as_of or _now()
    events = list(
        session.execute(
            select(MasteryEvent).where(MasteryEvent.concept_id == concept_id).order_by(MasteryEvent.occurred_at)
        ).scalars()
    )

    if not events:
        return ConceptMasteryResult(
            concept_id=concept_id, level=MasteryLevel.NO_EVIDENCE, score=None, event_count=0, last_reviewed=None, events=[]
        )

    weighted_sum = PRIOR_WEIGHT * PRIOR_SCORE
    weight_total = PRIOR_WEIGHT
    for event in events:
        age_days = max((as_of - event.occurred_at).total_seconds() / 86400.0, 0.0)
        weight = 0.5 ** (age_days / HALF_LIFE_DAYS)
        weighted_sum += event.outcome_score * weight
        weight_total += weight

    score = weighted_sum / weight_total
    return ConceptMasteryResult(
        concept_id=concept_id,
        level=_categorize(score),
        score=score,
        event_count=len(events),
        last_reviewed=events[-1].occurred_at,
        events=events,
    )
