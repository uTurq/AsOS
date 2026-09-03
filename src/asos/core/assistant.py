"""
The core assistant — where Claude actually gets invoked as the
reasoning engine, per architectural principle 1: local code
(asos.core.context) does all retrieval; Claude only synthesizes and
exercises judgment over what it's given.

Every prompt here explicitly instructs Claude to answer only from the
supplied context and to say so plainly if something isn't in it —
this is the guardrail against acceptance criterion 16's requirement
that a briefing never contains hallucinated content.
"""

from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from asos.core.context import build_context_snapshot, format_context_for_prompt
from asos.llm.client import ClaudeClient

SYSTEM_PREAMBLE = """You are AsOS (Assist Operating System), a personal academic assistant. \
You are given the user's real, current academic state below — schedule, tasks, upcoming \
assessments with an evidence-based preparedness breakdown, unresolved fact conflicts, and \
pending notifications. Base your response ONLY on this data. Never invent a deadline, grade, \
mastery level, or fact that isn't present in the context below. If the user asks about \
something not covered by the context, say plainly that you don't have that information rather \
than guessing. Be concise and conversational, not a bulleted data dump."""

BRIEFING_INSTRUCTIONS = """Generate a concise daily briefing from the context below. Cover, in \
this rough order, only where there's real content for it: today's schedule, any urgent tasks or \
deadlines, upcoming exams and specifically which concepts still need work (never claim someone \
is "ready" for an assessment they have no evidence for), any unresolved fact conflicts they \
should resolve, and a short recommended plan for today. Skip any section with nothing to report \
rather than saying "nothing to report" for it. Keep it tight — this is meant to be heard or read \
in under a minute, not a full report."""


def answer_query(
    session: Session, query: str, claude_client: ClaudeClient, *, as_of: datetime.datetime | None = None
) -> str:
    snapshot = build_context_snapshot(session, as_of=as_of)
    context_text = format_context_for_prompt(snapshot)
    prompt = f"{SYSTEM_PREAMBLE}\n\nCurrent context:\n{context_text}\n\nUser question: {query}"
    return claude_client.complete(prompt)


def generate_daily_briefing(
    session: Session, claude_client: ClaudeClient, *, as_of: datetime.datetime | None = None
) -> str:
    snapshot = build_context_snapshot(session, as_of=as_of)
    context_text = format_context_for_prompt(snapshot)
    prompt = f"{SYSTEM_PREAMBLE}\n\n{BRIEFING_INSTRUCTIONS}\n\nCurrent context:\n{context_text}"
    return claude_client.complete(prompt)
