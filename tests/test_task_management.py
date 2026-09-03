from __future__ import annotations

import pytest

from asos.db.enums import TaskState, TaskType
from asos.db.models import Assignment, Course
from asos.tasks.management import create_task, update_task_state


def _course(session) -> Course:
    course = Course(name="Physics 2210")
    session.add(course)
    session.commit()
    return course


def test_task_with_no_canvas_counterpart_can_be_created(session):
    course = _course(session)
    task = create_task(session, title="Review kinematics before quiz", task_type=TaskType.REVIEW, course_id=course.id)
    assert task.related_assignment_id is None
    assert task.state == TaskState.NOT_STARTED


def test_task_moves_through_all_five_states(session):
    course = _course(session)
    task = create_task(session, title="Read chapter 4", task_type=TaskType.READING, course_id=course.id)

    task = update_task_state(session, task.id, TaskState.IN_PROGRESS)
    assert task.state == TaskState.IN_PROGRESS

    task = update_task_state(session, task.id, TaskState.BLOCKED, blocked_reason="waiting on lecture notes")
    assert task.state == TaskState.BLOCKED
    assert task.blocked_reason == "waiting on lecture notes"

    task = update_task_state(session, task.id, TaskState.IN_PROGRESS)
    assert task.state == TaskState.IN_PROGRESS
    assert task.blocked_reason is None  # cleared on leaving BLOCKED

    task = update_task_state(session, task.id, TaskState.DONE)
    assert task.state == TaskState.DONE

    task2 = create_task(session, title="Optional extra reading", task_type=TaskType.READING, course_id=course.id)
    task2 = update_task_state(session, task2.id, TaskState.SKIPPED)
    assert task2.state == TaskState.SKIPPED


def test_blocked_requires_a_reason(session):
    course = _course(session)
    task = create_task(session, title="Do lab report", task_type=TaskType.WORKSHEET, course_id=course.id)
    with pytest.raises(ValueError, match="blocked_reason"):
        update_task_state(session, task.id, TaskState.BLOCKED)


def test_marking_canvas_linked_task_done_does_not_touch_canvas_status(session):
    """Acceptance criterion 11."""
    course = _course(session)
    assignment = Assignment(course_id=course.id, title="Lab Report 2", canvas_status="unsubmitted")
    session.add(assignment)
    session.commit()

    task = create_task(
        session, title="Do Lab Report 2", task_type=TaskType.WORKSHEET, course_id=course.id,
        related_assignment_id=assignment.id,
    )
    update_task_state(session, task.id, TaskState.DONE)

    refreshed_assignment = session.get(Assignment, assignment.id)
    assert refreshed_assignment.canvas_status == "unsubmitted"  # untouched


def test_update_nonexistent_task_raises_clear_error(session):
    with pytest.raises(LookupError):
        update_task_state(session, 99999, TaskState.DONE)
