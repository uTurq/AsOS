from __future__ import annotations

from sqlalchemy import select

from asos.canvas.client import CanvasClient
from asos.canvas.sync import CanvasSyncWorker
from asos.db.enums import SyncChangeType, SyncEntityType
from asos.db.models import Assignment, Course, SyncChangeLogEntry
from tests.canvas_fakes import FakeCanvasSession, FakeResponse

BASE_URL = "https://school.instructure.com"


def _client_with(session: FakeCanvasSession) -> CanvasClient:
    return CanvasClient(BASE_URL, token="tok", session=session)


def _register_standard_routes(fake_session: FakeCanvasSession, *, due_at: str = "2026-10-14T23:59:00Z"):
    fake_session.add(
        f"{BASE_URL}/api/v1/courses",
        {"enrollment_state": "active", "per_page": 100},
        FakeResponse([{"id": 501, "name": "Chemistry 1010", "term": {"name": "Fall 2026"}}]),
    )
    fake_session.add(
        f"{BASE_URL}/api/v1/courses/501/assignments",
        {"include[]": "submission", "per_page": 100},
        FakeResponse(
            [
                {
                    "id": 9001,
                    "name": "Exam 1",
                    "due_at": due_at,
                    "points_possible": 100,
                    "submission": {"workflow_state": "unsubmitted"},
                }
            ]
        ),
    )
    fake_session.add(
        f"{BASE_URL}/api/v1/calendar_events",
        {"context_codes[]": ["course_501"], "type": "event", "per_page": 100},
        FakeResponse([]),
    )


def test_initial_sync_creates_course_and_assignment(session):
    fake_session = FakeCanvasSession()
    _register_standard_routes(fake_session)
    worker = CanvasSyncWorker(_client_with(fake_session))

    summary = worker.sync_all(session)

    assert summary == {"courses": 1, "assignments": 1, "calendar_events": 0, "changes_detected": 2}

    course = session.execute(select(Course)).scalar_one()
    assert course.name == "Chemistry 1010"
    assert course.canvas_course_id == "501"

    assignment = session.execute(select(Assignment)).scalar_one()
    assert assignment.title == "Exam 1"
    assert assignment.canvas_status == "unsubmitted"

    change_log = session.execute(select(SyncChangeLogEntry)).scalars().all()
    assert len(change_log) == 2
    assert {c.change_type for c in change_log} == {SyncChangeType.CREATED}
    assert {c.entity_type for c in change_log} == {SyncEntityType.COURSE, SyncEntityType.ASSIGNMENT}


def test_resync_with_no_changes_produces_no_new_diff_entries(session):
    fake_session = FakeCanvasSession()
    _register_standard_routes(fake_session)
    worker = CanvasSyncWorker(_client_with(fake_session))

    worker.sync_all(session)
    first_run_count = len(session.execute(select(SyncChangeLogEntry)).scalars().all())

    # Re-register identical routes (a fresh "poll") and sync again.
    _register_standard_routes(fake_session)
    summary = worker.sync_all(session)

    assert summary["changes_detected"] == 0
    second_run_total = len(session.execute(select(SyncChangeLogEntry)).scalars().all())
    assert second_run_total == first_run_count  # nothing new logged


def test_resync_with_moved_due_date_logs_diff_and_retains_old_value(session):
    fake_session = FakeCanvasSession()
    _register_standard_routes(fake_session, due_at="2026-10-14T23:59:00Z")
    worker = CanvasSyncWorker(_client_with(fake_session))
    worker.sync_all(session)

    # Simulate Canvas-side change: exam moved two days later.
    fake_session2 = FakeCanvasSession()
    _register_standard_routes(fake_session2, due_at="2026-10-16T23:59:00Z")
    worker2 = CanvasSyncWorker(_client_with(fake_session2))
    summary = worker2.sync_all(session)

    assert summary["changes_detected"] == 1  # only due_at changed

    assignment = session.execute(select(Assignment)).scalar_one()
    # Naive UTC by convention (see asos.db.base._now docstring) — no
    # offset suffix, but still the correct instant.
    assert assignment.due_at.isoformat() == "2026-10-16T23:59:00"
    assert assignment.due_at.tzinfo is None

    diff_entries = session.execute(
        select(SyncChangeLogEntry).where(SyncChangeLogEntry.field_name == "due_at")
    ).scalars().all()
    assert len(diff_entries) == 1
    diff = diff_entries[0]
    assert diff.change_type == SyncChangeType.UPDATED
    assert "2026-10-14" in diff.old_value  # old value is retained, not overwritten away
    assert "2026-10-16" in diff.new_value


def test_due_at_survives_identity_map_eviction_and_reload(session):
    """Regression test for a real bug caught during development: SQLite
    doesn't preserve timezone-aware datetimes across a reload once an
    object falls out of SQLAlchemy's identity map (e.g. after a service
    restart). Storing naive UTC everywhere means a fresh reload compares
    equal to a freshly-parsed value with no aware/naive mismatch."""
    import gc

    fake_session = FakeCanvasSession()
    _register_standard_routes(fake_session, due_at="2026-10-14T23:59:00Z")
    worker = CanvasSyncWorker(_client_with(fake_session))
    worker.sync_all(session)

    # Drop every Python reference to the ORM objects and force garbage
    # collection so SQLAlchemy's (weak-ref) identity map actually loses
    # them, forcing the next query to genuinely reload from SQLite.
    session.expunge_all()
    gc.collect()

    reloaded = session.execute(select(Assignment)).scalar_one()
    assert reloaded.due_at.tzinfo is None

    # Re-syncing the identical due date after a reload must NOT be seen
    # as a change — this is exactly the bug that was caught.
    fake_session2 = FakeCanvasSession()
    _register_standard_routes(fake_session2, due_at="2026-10-14T23:59:00Z")
    worker2 = CanvasSyncWorker(_client_with(fake_session2))
    summary = worker2.sync_all(session)
    assert summary["changes_detected"] == 0


def test_grade_status_change_is_tracked_independently_of_local_task_state(session):
    """canvas_status changing must not touch any local task — sync only
    ever writes courses/assignments/calendar_events/sync_change_log."""
    from asos.db.enums import TaskState, TaskType
    from asos.db.models import Task

    fake_session = FakeCanvasSession()
    _register_standard_routes(fake_session)
    worker = CanvasSyncWorker(_client_with(fake_session))
    worker.sync_all(session)

    assignment = session.execute(select(Assignment)).scalar_one()
    task = Task(
        course_id=assignment.course_id,
        related_assignment_id=assignment.id,
        title="Study for Exam 1",
        task_type=TaskType.PREP,
        state=TaskState.DONE,
    )
    session.add(task)
    session.commit()

    # Canvas now reports the assignment as graded.
    fake_session2 = FakeCanvasSession()
    fake_session2.add(
        f"{BASE_URL}/api/v1/courses",
        {"enrollment_state": "active", "per_page": 100},
        FakeResponse([{"id": 501, "name": "Chemistry 1010", "term": {"name": "Fall 2026"}}]),
    )
    fake_session2.add(
        f"{BASE_URL}/api/v1/courses/501/assignments",
        {"include[]": "submission", "per_page": 100},
        FakeResponse(
            [
                {
                    "id": 9001,
                    "name": "Exam 1",
                    "due_at": "2026-10-14T23:59:00Z",
                    "points_possible": 100,
                    "submission": {"workflow_state": "graded"},
                }
            ]
        ),
    )
    fake_session2.add(
        f"{BASE_URL}/api/v1/calendar_events",
        {"context_codes[]": ["course_501"], "type": "event", "per_page": 100},
        FakeResponse([]),
    )
    worker2 = CanvasSyncWorker(_client_with(fake_session2))
    worker2.sync_all(session)

    refreshed_task = session.get(Task, task.id)
    assert refreshed_task.state == TaskState.DONE  # untouched by the Canvas-side change
