"""Scans current assessments/tasks with due dates, classifies urgency,
and upserts notifications. This is the piece a future scheduler tick
or `asos notifications scan` calls; it's the seed of proactive
behavior, not the full daily-briefing synthesis (that's a later
milestone)."""

from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from asos.assessments.preparedness import compute_assessment_preparedness
from asos.db.base import _now
from asos.db.models import Assessment, Notification, Task
from asos.notifications.classification import classify_assessment_urgency, classify_task_urgency
from asos.notifications.delivery import upsert_notification_for_target


def scan_for_notifications(session: Session, *, as_of: datetime.datetime | None = None) -> list[Notification]:
    as_of = as_of or _now()
    results: list[Notification] = []

    assessments = session.execute(select(Assessment).where(Assessment.date.is_not(None))).scalars().all()
    for assessment in assessments:
        hours_until = (assessment.date - as_of).total_seconds() / 3600.0
        prep = compute_assessment_preparedness(session, assessment.id, as_of=as_of)
        severity = classify_assessment_urgency(prep, hours_until=hours_until)
        if severity is None:
            continue

        weak_spots = [c.concept.name for c in prep.weak + prep.no_evidence]
        weak_summary = ", ".join(weak_spots) if weak_spots else "some material"
        result = upsert_notification_for_target(
            session,
            severity=severity,
            title=f"{assessment.name} is coming up",
            body=f"{assessment.name} is in about {hours_until:.0f} hours. Still shaky on: {weak_summary}.",
            related_course_id=assessment.course_id,
            related_assessment_id=assessment.id,
        )
        if result is not None:
            results.append(result)

    tasks = session.execute(select(Task).where(Task.due_at.is_not(None))).scalars().all()
    for task in tasks:
        hours_until = (task.due_at - as_of).total_seconds() / 3600.0
        severity = classify_task_urgency(task, hours_until=hours_until)
        if severity is None:
            continue

        result = upsert_notification_for_target(
            session,
            severity=severity,
            title=f"Task due soon: {task.title}",
            body=f"'{task.title}' is due in about {hours_until:.0f} hours (currently {task.state.value}).",
            related_course_id=task.course_id,
            related_task_id=task.id,
        )
        if result is not None:
            results.append(result)

    return results
