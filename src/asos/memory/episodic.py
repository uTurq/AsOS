"""
Episodic notes — the semantic-memory tier from the locked design.

Deliberately just a storage function, not an "automatically summarize
every conversation" pipeline. Deciding WHAT is worth remembering from
a conversation is itself a judgment call for Claude to make (e.g. "the
user mentioned they always struggle with reaction mechanisms right
before exams"), not something this module infers on its own — this
function is the write path such a decision flows through, not the
decision-maker. Wiring an actual "after each voice session, extract a
note" pipeline is deferred to the voice-lite milestone, since that's
when there's a real conversation loop to hook into.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from asos.db.base import _now
from asos.db.models import EpisodicNote


def record_episodic_note(
    session: Session, *, content: str, course_id: int | None = None, concept_id: int | None = None
) -> EpisodicNote:
    note = EpisodicNote(course_id=course_id, concept_id=concept_id, content=content, created_at=_now())
    session.add(note)
    session.commit()
    return note
