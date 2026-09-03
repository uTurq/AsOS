from __future__ import annotations

import datetime

from asos.core.assistant import answer_query, generate_daily_briefing
from asos.db.enums import TaskState, TaskType
from asos.db.models import Course, Task

NOW = datetime.datetime(2026, 9, 3, 10, 0, 0)


class FakeClaudeClient:
    def __init__(self, response: str = "Here's your briefing."):
        self._response = response
        self.last_prompt: str | None = None

    def complete(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self._response


def _course_with_task(session) -> Task:
    course = Course(name="Chemistry 1010")
    session.add(course)
    session.commit()
    task = Task(course_id=course.id, title="UNIQUE_TASK_MARKER_XYZ", task_type=TaskType.READING, state=TaskState.NOT_STARTED)
    session.add(task)
    session.commit()
    return task


def test_answer_query_grounds_prompt_in_real_context(session):
    _course_with_task(session)
    client = FakeClaudeClient()

    answer_query(session, "what should I do right now?", client, as_of=NOW)

    assert "UNIQUE_TASK_MARKER_XYZ" in client.last_prompt
    assert "what should I do right now?" in client.last_prompt


def test_answer_query_returns_claude_response(session):
    client = FakeClaudeClient(response="You should read chapter 4.")
    result = answer_query(session, "what should I study?", client, as_of=NOW)
    assert result == "You should read chapter 4."


def test_answer_query_includes_grounding_instruction(session):
    """The prompt must instruct Claude not to hallucinate beyond the
    supplied context — this is the guardrail, not Claude's actual
    behavior, which this test can't verify."""
    client = FakeClaudeClient()
    answer_query(session, "anything", client, as_of=NOW)
    assert "Never invent" in client.last_prompt


def test_briefing_grounds_prompt_in_real_context(session):
    _course_with_task(session)
    client = FakeClaudeClient()

    generate_daily_briefing(session, client, as_of=NOW)

    assert "UNIQUE_TASK_MARKER_XYZ" in client.last_prompt
    assert "briefing" in client.last_prompt.lower()


def test_briefing_returns_claude_response(session):
    client = FakeClaudeClient(response="Good morning! Here's your day.")
    result = generate_daily_briefing(session, client, as_of=NOW)
    assert result == "Good morning! Here's your day."


def test_briefing_with_empty_state_still_produces_valid_prompt(session):
    """No courses, no tasks, nothing scheduled — the prompt should
    still be well-formed, not error out."""
    client = FakeClaudeClient()
    generate_daily_briefing(session, client, as_of=NOW)
    assert "(nothing scheduled)" in client.last_prompt
