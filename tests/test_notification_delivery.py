from __future__ import annotations

import datetime

from asos.db.enums import NotificationSeverity, TaskState, TaskType
from asos.db.models import Course, Task
from asos.notifications.delivery import (
    get_ambient_log,
    get_deliverable_critical_notifications,
    get_notable_notifications_for_briefing,
    is_quiet_hours,
    upsert_notification_for_target,
)

NOW = datetime.datetime(2026, 9, 1, 14, 0, 0)  # 2pm, not quiet hours


def _task(session) -> Task:
    course = Course(name="Physics 2210")
    session.add(course)
    session.commit()
    task = Task(course_id=course.id, title="Lab report", task_type=TaskType.WORKSHEET, state=TaskState.NOT_STARTED)
    session.add(task)
    session.commit()
    return task


def test_is_quiet_hours_wraps_midnight():
    assert is_quiet_hours(datetime.datetime(2026, 1, 1, 23, 0)) is True
    assert is_quiet_hours(datetime.datetime(2026, 1, 1, 3, 0)) is True
    assert is_quiet_hours(datetime.datetime(2026, 1, 1, 14, 0)) is False
    assert is_quiet_hours(datetime.datetime(2026, 1, 1, 8, 0)) is False  # boundary: end_hour excluded
    assert is_quiet_hours(datetime.datetime(2026, 1, 1, 22, 0)) is True  # boundary: start_hour included


def test_new_target_creates_a_notification(session):
    task = _task(session)
    n = upsert_notification_for_target(
        session, severity=NotificationSeverity.NOTABLE, title="t", body="b", related_task_id=task.id
    )
    assert n is not None
    assert n.severity == NotificationSeverity.NOTABLE


def test_escalation_updates_in_place_not_a_duplicate(session):
    task = _task(session)
    first = upsert_notification_for_target(
        session, severity=NotificationSeverity.AMBIENT, title="early heads up", body="b", related_task_id=task.id
    )
    second = upsert_notification_for_target(
        session, severity=NotificationSeverity.CRITICAL, title="urgent now", body="b2", related_task_id=task.id
    )
    assert second.id == first.id  # same row, escalated
    assert second.severity == NotificationSeverity.CRITICAL
    assert second.title == "urgent now"

    from asos.db.models import Notification

    all_for_task = session.query(Notification).filter_by(related_task_id=task.id).all()
    assert len(all_for_task) == 1  # never duplicated


def test_never_downgrades_silently(session):
    task = _task(session)
    upsert_notification_for_target(
        session, severity=NotificationSeverity.CRITICAL, title="urgent", body="b", related_task_id=task.id
    )
    result = upsert_notification_for_target(
        session, severity=NotificationSeverity.AMBIENT, title="less urgent now", body="b2", related_task_id=task.id
    )
    assert result is None  # no change made

    from asos.db.models import Notification

    n = session.query(Notification).filter_by(related_task_id=task.id).one()
    assert n.severity == NotificationSeverity.CRITICAL  # still critical, not downgraded
    assert n.title == "urgent"  # unchanged


def test_delivered_notification_does_not_block_a_new_one_for_same_target(session):
    """Once a notification is delivered (resolved), a fresh issue for
    the same task should be able to create a new one rather than being
    silently swallowed by dedup logic."""
    task = _task(session)
    first = upsert_notification_for_target(
        session, severity=NotificationSeverity.CRITICAL, title="first", body="b", related_task_id=task.id
    )
    first.delivered = True
    session.commit()

    second = upsert_notification_for_target(
        session, severity=NotificationSeverity.NOTABLE, title="second", body="b2", related_task_id=task.id
    )
    assert second.id != first.id


def test_critical_delivered_outside_quiet_hours_respecting_rate_limit(session):
    task1 = _task(session)
    task2 = _task(session)
    task3 = _task(session)
    for t in (task1, task2, task3):
        upsert_notification_for_target(
            session, severity=NotificationSeverity.CRITICAL, title=f"urgent {t.id}", body="b", related_task_id=t.id
        )

    delivered = get_deliverable_critical_notifications(session, as_of=NOW, max_per_day=2)
    assert len(delivered) == 2  # rate limited to 2
    assert all(n.delivered for n in delivered)

    # A second scan later the same day should deliver nothing more —
    # quota already spent.
    delivered_again = get_deliverable_critical_notifications(session, as_of=NOW, max_per_day=2)
    assert delivered_again == []


def test_critical_never_delivered_during_quiet_hours(session):
    task = _task(session)
    upsert_notification_for_target(
        session, severity=NotificationSeverity.CRITICAL, title="urgent", body="b", related_task_id=task.id
    )
    quiet_time = datetime.datetime(2026, 9, 1, 23, 30)
    delivered = get_deliverable_critical_notifications(session, as_of=quiet_time)
    assert delivered == []


def test_notable_bundled_and_marked_delivered_on_briefing_pull(session):
    task = _task(session)
    upsert_notification_for_target(
        session, severity=NotificationSeverity.NOTABLE, title="fyi", body="b", related_task_id=task.id
    )
    bundle = get_notable_notifications_for_briefing(session, as_of=NOW)
    assert len(bundle) == 1
    assert bundle[0].delivered is True

    # Pulling again should find nothing left to bundle.
    assert get_notable_notifications_for_briefing(session, as_of=NOW) == []


def test_ambient_never_auto_delivered(session):
    task = _task(session)
    upsert_notification_for_target(
        session, severity=NotificationSeverity.AMBIENT, title="minor thing", body="b", related_task_id=task.id
    )
    log = get_ambient_log(session)
    assert len(log) == 1
    assert log[0].delivered is False  # querying it doesn't mark it delivered

    # Asking again still finds it — ambient items don't get consumed.
    assert len(get_ambient_log(session)) == 1
