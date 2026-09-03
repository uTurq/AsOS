"""
Notification severity classification.

Pure functions, no DB access — deliberately separate from
asos.notifications.delivery (which handles persistence, dedup/
escalation, rate limiting, and quiet hours). This split mirrors
asos.documents.parsing/chunking vs. ingestion/retrieval: the judgment
call (how urgent is this?) is independently testable from the
plumbing (how do we store and rate-limit it?).

Severity tiers, per the locked design:
  CRITICAL — interrupts (subject to quiet hours + a daily rate limit).
    e.g. an exam in under 48h with real weak spots; a task due in under
    12h that hasn't been started.
  NOTABLE  — bundled for the next natural touchpoint (a briefing pull),
    never pushed on its own.
  AMBIENT  — logged only; surfaces only if explicitly asked for.
"""

from __future__ import annotations

from asos.assessments.preparedness import AssessmentPreparedness
from asos.db.enums import NotificationSeverity, TaskState
from asos.db.models import Task

_INACTIVE_TASK_STATES = (TaskState.DONE, TaskState.SKIPPED)


def classify_assessment_urgency(prep: AssessmentPreparedness, *, hours_until: float) -> NotificationSeverity | None:
    """None means nothing worth surfacing about this assessment right now."""
    if hours_until < 0:
        return None

    has_weak_spots = bool(prep.weak or prep.no_evidence)
    if not has_weak_spots:
        return None  # well-prepared — nothing to say

    if hours_until <= 48:
        return NotificationSeverity.CRITICAL
    if hours_until <= 72:
        return NotificationSeverity.NOTABLE
    if hours_until <= 168:  # within a week
        return NotificationSeverity.AMBIENT
    return None


def classify_task_urgency(task: Task, *, hours_until: float) -> NotificationSeverity | None:
    if hours_until < 0 or task.state in _INACTIVE_TASK_STATES:
        return None

    if hours_until <= 12:
        return NotificationSeverity.CRITICAL
    if hours_until <= 72:
        return NotificationSeverity.NOTABLE
    if hours_until <= 168:
        return NotificationSeverity.AMBIENT
    return None
