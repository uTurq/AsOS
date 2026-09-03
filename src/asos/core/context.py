"""
Context assembly.

This is the "local retrieval" half of the architecture's core
principle: everything here is plain queries and computation, no LLM
call. Claude (asos.core.assistant) only ever sees the OUTPUT of this
module — a compact, factual snapshot — never raw DB access. That
boundary matters for two reasons: it keeps Claude calls cheap (a
handful of KB of text, not a full session dump), and it means every
fact Claude is given is something a person could point to in the
database, not something Claude inferred or hallucinated.

Building a snapshot is read-only and idempotent — it never marks a
notification delivered or otherwise mutates state (unlike
asos.notifications.delivery's consumption functions), so it's safe to
call as often as needed (e.g. once per "what should I do right now?"
query) without side effects.
"""

from __future__ import annotations

import dataclasses
import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from asos.assessments.preparedness import AssessmentPreparedness, compute_assessment_preparedness
from asos.db.base import _now
from asos.db.enums import TaskState
from asos.db.models import Assessment, AssessmentConcept, CalendarEvent, Notification, Task
from asos.facts.authority import FactResolution, find_all_conflicts

DEFAULT_ASSESSMENT_WINDOW_DAYS = 14


@dataclasses.dataclass
class ContextSnapshot:
    as_of: datetime.datetime
    todays_events: list[CalendarEvent]
    open_tasks: list[Task]
    upcoming_assessments: list[tuple[Assessment, AssessmentPreparedness | None]]
    unresolved_conflicts: list[FactResolution]
    pending_notifications: list[Notification]


def build_context_snapshot(
    session: Session,
    *,
    as_of: datetime.datetime | None = None,
    assessment_window_days: int = DEFAULT_ASSESSMENT_WINDOW_DAYS,
) -> ContextSnapshot:
    as_of = as_of or _now()
    day_start = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + datetime.timedelta(days=1)

    todays_events = list(
        session.execute(
            select(CalendarEvent)
            .where(CalendarEvent.start_at >= day_start, CalendarEvent.start_at < day_end)
            .order_by(CalendarEvent.start_at)
        ).scalars()
    )

    open_tasks = list(
        session.execute(
            select(Task)
            .where(Task.state.notin_([TaskState.DONE, TaskState.SKIPPED]))
            .order_by(Task.due_at)
        ).scalars()
    )

    window_end = as_of + datetime.timedelta(days=assessment_window_days)
    upcoming_assessment_rows = list(
        session.execute(
            select(Assessment)
            .where(Assessment.date.is_not(None), Assessment.date >= as_of, Assessment.date <= window_end)
            .order_by(Assessment.date)
        ).scalars()
    )
    upcoming_assessments = []
    for assessment in upcoming_assessment_rows:
        has_links = (
            session.execute(
                select(AssessmentConcept).where(AssessmentConcept.assessment_id == assessment.id)
            ).first()
            is not None
        )
        prep = compute_assessment_preparedness(session, assessment.id, as_of=as_of) if has_links else None
        upcoming_assessments.append((assessment, prep))

    unresolved_conflicts = find_all_conflicts(session)

    pending_notifications = list(
        session.execute(
            select(Notification).where(Notification.delivered.is_(False)).order_by(Notification.created_at)
        ).scalars()
    )

    return ContextSnapshot(
        as_of=as_of,
        todays_events=todays_events,
        open_tasks=open_tasks,
        upcoming_assessments=upcoming_assessments,
        unresolved_conflicts=unresolved_conflicts,
        pending_notifications=pending_notifications,
    )


def format_context_for_prompt(snapshot: ContextSnapshot) -> str:
    """Renders a snapshot into compact text for a Claude prompt. Kept
    deliberately plain (no markdown tables, no fluff) — this is data
    for Claude to reason over, not something a person reads directly."""
    lines = [f"Current time: {snapshot.as_of.isoformat()}", ""]

    lines.append("Today's schedule:")
    if snapshot.todays_events:
        for e in snapshot.todays_events:
            lines.append(f"  - {e.start_at.strftime('%H:%M')} {e.title} ({e.event_type.value})")
    else:
        lines.append("  (nothing scheduled)")

    lines.append("")
    lines.append("Open tasks:")
    if snapshot.open_tasks:
        for t in snapshot.open_tasks:
            due = f", due {t.due_at.isoformat()}" if t.due_at else ""
            lines.append(f"  - [{t.state.value}] {t.title}{due}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("Upcoming assessments:")
    if snapshot.upcoming_assessments:
        for assessment, prep in snapshot.upcoming_assessments:
            lines.append(f"  - {assessment.name} on {assessment.date.isoformat()}")
            if prep is None:
                lines.append("      (no concepts linked yet — preparedness unknown)")
            else:
                if prep.strong:
                    lines.append(f"      Strong: {', '.join(c.concept.name for c in prep.strong)}")
                if prep.developing:
                    lines.append(f"      Developing: {', '.join(c.concept.name for c in prep.developing)}")
                if prep.weak:
                    lines.append(f"      Weak: {', '.join(c.concept.name for c in prep.weak)}")
                if prep.no_evidence:
                    lines.append(f"      Not yet studied: {', '.join(c.concept.name for c in prep.no_evidence)}")
                lines.append(f"      Coverage: {prep.coverage:.0%}")
    else:
        lines.append("  (none in the next window)")

    lines.append("")
    lines.append("Unresolved fact conflicts:")
    if snapshot.unresolved_conflicts:
        for resolution in snapshot.unresolved_conflicts:
            values = "; ".join(f"'{f.value}' (source: {f.source.type.value})" for f in resolution.conflicting)
            lines.append(f"  - {resolution.subject}: {values}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("Pending notifications:")
    if snapshot.pending_notifications:
        for n in snapshot.pending_notifications:
            lines.append(f"  - [{n.severity.value}] {n.title}: {n.body}")
    else:
        lines.append("  (none)")

    return "\n".join(lines)
