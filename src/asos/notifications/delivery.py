"""
Notification delivery/persistence.

Three guardrails locked in the design, all enforced here:
  1. Escalation only, never silent de-escalation. If a notification
     already exists (undelivered) for the same task/assessment,
     `upsert_notification_for_target` only ever raises its severity,
     never lowers it, and never creates a duplicate for the same
     target.
  2. Quiet hours. CRITICAL notifications are never surfaced as an
     interrupt during quiet hours — they just wait.
  3. A daily rate limit on CRITICAL interrupts, so AsOS can't turn into
     something the user disables within a week.

NOTABLE notifications are never "delivered now" by this module at
all — they're bundled and only marked delivered when a briefing/
touchpoint pulls them (get_notable_notifications_for_briefing).
AMBIENT notifications are never marked delivered automatically; they
just sit in the log until explicitly asked for.
"""

from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from asos.db.base import _now
from asos.db.enums import NotificationSeverity
from asos.db.models import Notification

DEFAULT_MAX_CRITICAL_PER_DAY = 2
DEFAULT_QUIET_HOURS = (22, 8)  # 10pm - 8am, wraps midnight

_SEVERITY_RANK = {
    NotificationSeverity.AMBIENT: 0,
    NotificationSeverity.NOTABLE: 1,
    NotificationSeverity.CRITICAL: 2,
}


def is_quiet_hours(dt: datetime.datetime, *, start_hour: int = DEFAULT_QUIET_HOURS[0], end_hour: int = DEFAULT_QUIET_HOURS[1]) -> bool:
    hour = dt.hour
    if start_hour > end_hour:  # wraps midnight, e.g. 22 -> 8
        return hour >= start_hour or hour < end_hour
    return start_hour <= hour < end_hour


def upsert_notification_for_target(
    session: Session,
    *,
    severity: NotificationSeverity,
    title: str,
    body: str,
    related_course_id: int | None = None,
    related_task_id: int | None = None,
    related_assessment_id: int | None = None,
) -> Notification | None:
    """Creates a notification, or escalates an existing undelivered one
    for the same task/assessment if the new severity is higher. Never
    creates a duplicate, never downgrades. Returns None if nothing
    changed (an existing notification already matches or exceeds the
    new severity)."""
    existing = None
    if related_task_id is not None:
        existing = session.execute(
            select(Notification).where(
                Notification.related_task_id == related_task_id, Notification.delivered.is_(False)
            )
        ).scalars().first()
    elif related_assessment_id is not None:
        existing = session.execute(
            select(Notification).where(
                Notification.related_assessment_id == related_assessment_id, Notification.delivered.is_(False)
            )
        ).scalars().first()

    if existing is None:
        notification = Notification(
            severity=severity,
            title=title,
            body=body,
            related_course_id=related_course_id,
            related_task_id=related_task_id,
            related_assessment_id=related_assessment_id,
        )
        session.add(notification)
        session.commit()
        return notification

    if _SEVERITY_RANK[severity] > _SEVERITY_RANK[existing.severity]:
        existing.severity = severity
        existing.title = title
        existing.body = body
        session.commit()
        return existing

    return None


def get_deliverable_critical_notifications(
    session: Session,
    *,
    as_of: datetime.datetime | None = None,
    max_per_day: int = DEFAULT_MAX_CRITICAL_PER_DAY,
    quiet_hours: tuple[int, int] = DEFAULT_QUIET_HOURS,
) -> list[Notification]:
    """Returns the CRITICAL notifications that should interrupt right
    now, respecting quiet hours and the daily rate limit. Marks
    whatever it returns as delivered."""
    as_of = as_of or _now()

    if is_quiet_hours(as_of, start_hour=quiet_hours[0], end_hour=quiet_hours[1]):
        return []

    day_start = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    already_today = session.execute(
        select(Notification).where(
            Notification.severity == NotificationSeverity.CRITICAL,
            Notification.delivered.is_(True),
            Notification.delivered_at >= day_start,
        )
    ).scalars().all()
    remaining_quota = max_per_day - len(already_today)
    if remaining_quota <= 0:
        return []

    undelivered = session.execute(
        select(Notification)
        .where(Notification.severity == NotificationSeverity.CRITICAL, Notification.delivered.is_(False))
        .order_by(Notification.created_at)
    ).scalars().all()

    to_deliver = list(undelivered[:remaining_quota])
    for n in to_deliver:
        n.delivered = True
        n.delivered_at = as_of
    if to_deliver:
        session.commit()
    return to_deliver


def get_notable_notifications_for_briefing(
    session: Session, *, course_id: int | None = None, as_of: datetime.datetime | None = None
) -> list[Notification]:
    """Bundled NOTABLE notifications — call this when a briefing/
    touchpoint happens. Marks what it returns as delivered, since a
    briefing IS the delivery mechanism for this tier."""
    as_of = as_of or _now()
    stmt = select(Notification).where(
        Notification.severity == NotificationSeverity.NOTABLE, Notification.delivered.is_(False)
    )
    if course_id is not None:
        stmt = stmt.where(Notification.related_course_id == course_id)

    notable = list(session.execute(stmt.order_by(Notification.created_at)).scalars().all())
    for n in notable:
        n.delivered = True
        n.delivered_at = as_of
    if notable:
        session.commit()
    return notable


def get_ambient_log(session: Session, *, course_id: int | None = None) -> list[Notification]:
    """AMBIENT notifications are never auto-delivered — this is the
    on-demand 'anything low-priority I should know?' query."""
    stmt = select(Notification).where(Notification.severity == NotificationSeverity.AMBIENT)
    if course_id is not None:
        stmt = stmt.where(Notification.related_course_id == course_id)
    return list(session.execute(stmt.order_by(Notification.created_at)).scalars().all())
