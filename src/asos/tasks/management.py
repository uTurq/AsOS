"""
Task management.

Tasks are deliberately independent of Canvas: `related_assignment_id`
is optional (many real study tasks — reading, review, prep — have no
Canvas counterpart at all), and nothing here ever reads or writes
`Assignment.canvas_status`. See PROJECT.md's architectural principles.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from asos.db.enums import TaskState, TaskType
from asos.db.models import Task


def create_task(
    session: Session,
    *,
    title: str,
    task_type: TaskType,
    course_id: int | None = None,
    related_assignment_id: int | None = None,
    due_at=None,
) -> Task:
    task = Task(
        course_id=course_id,
        related_assignment_id=related_assignment_id,
        title=title,
        task_type=task_type,
        state=TaskState.NOT_STARTED,
        due_at=due_at,
    )
    session.add(task)
    session.commit()
    return task


def update_task_state(
    session: Session, task_id: int, new_state: TaskState, *, blocked_reason: str | None = None
) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise LookupError(f"No task with id {task_id}")

    if new_state == TaskState.BLOCKED and not blocked_reason:
        raise ValueError("blocked_reason is required when moving a task to BLOCKED")

    task.state = new_state
    # Clear any stale blocked_reason the moment the task leaves BLOCKED —
    # otherwise a resolved blocker's explanation would linger forever.
    task.blocked_reason = blocked_reason if new_state == TaskState.BLOCKED else None
    session.commit()
    return task
