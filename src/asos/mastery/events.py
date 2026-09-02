"""
Recording mastery evidence.

Every call here is an INSERT, never an UPDATE — mastery_events is an
append-only ledger by design (see PROJECT.md). There is no
"update_mastery" function and there never should be one.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from asos.db.base import _now
from asos.db.enums import MasteryEventType, MasteryOutcome
from asos.db.models import MasteryEvent

_OUTCOME_DEFAULT_SCORES = {
    MasteryOutcome.CORRECT: 1.0,
    MasteryOutcome.INCORRECT: 0.0,
    MasteryOutcome.PARTIAL: 0.5,
}


def record_mastery_event(
    session: Session,
    *,
    concept_id: int,
    event_type: MasteryEventType,
    outcome: MasteryOutcome,
    outcome_score: float | None = None,
    self_rating: int | None = None,
    source_description: str | None = None,
    notes: str | None = None,
    occurred_at=None,
) -> MasteryEvent:
    """Records one piece of mastery evidence. If outcome_score isn't
    given explicitly, a sensible default is derived from `outcome`
    (CORRECT=1.0, INCORRECT=0.0, PARTIAL=0.5), or from `self_rating`
    (1-5 -> 0.0-1.0) when outcome=SELF_RATED. Pass outcome_score
    explicitly for anything more specific (e.g. partial quiz credit)."""
    if outcome_score is None:
        if outcome == MasteryOutcome.SELF_RATED:
            if self_rating is None:
                raise ValueError("self_rating is required when outcome=SELF_RATED and outcome_score isn't given")
            outcome_score = (self_rating - 1) / 4.0
        else:
            outcome_score = _OUTCOME_DEFAULT_SCORES[outcome]

    event = MasteryEvent(
        concept_id=concept_id,
        event_type=event_type,
        outcome=outcome,
        outcome_score=outcome_score,
        self_rating=self_rating,
        source_description=source_description,
        notes=notes,
        occurred_at=occurred_at or _now(),
    )
    session.add(event)
    session.commit()
    return event
