from __future__ import annotations

import pytest

from asos.db.models import Course, Document
from asos.db.enums import DocumentSourceType, FactConfidence
from asos.documents.extraction import ExtractionError, extract_syllabus_facts
from asos.facts.authority import get_current_facts, seed_default_sources


class FakeClaudeClient:
    def __init__(self, response: str):
        self._response = response
        self.last_prompt: str | None = None

    def complete(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self._response


def _course_and_document(session):
    course = Course(name="Chemistry 1010")
    session.add(course)
    session.commit()
    document = Document(
        course_id=course.id, title="Syllabus", source_type=DocumentSourceType.SYLLABUS, file_path="/fake/path"
    )
    session.add(document)
    session.commit()
    return course, document


def test_extracts_facts_from_valid_json_response(session):
    seed_default_sources(session)
    course, document = _course_and_document(session)

    client = FakeClaudeClient(
        '[{"subject": "Exam 1 date", "value": "October 14"}, '
        '{"subject": "Late policy", "value": "10% per day"}]'
    )

    facts = extract_syllabus_facts(
        session,
        course_id=course.id,
        document_id=document.id,
        syllabus_text="Exam 1 is on October 14. Late work loses 10% per day.",
        claude_client=client,
    )

    assert len(facts) == 2
    subjects = {f.subject for f in facts}
    assert subjects == {"Exam 1 date", "Late policy"}
    assert all(f.confidence == FactConfidence.MEDIUM for f in facts)
    assert all(f.document_id == document.id for f in facts)

    # Facts are actually queryable via the authority engine afterward.
    current = get_current_facts(session, course_id=course.id, subject="Exam 1 date")
    assert len(current) == 1
    assert current[0].value == "October 14"


def test_empty_array_response_extracts_nothing(session):
    seed_default_sources(session)
    course, document = _course_and_document(session)
    client = FakeClaudeClient("[]")

    facts = extract_syllabus_facts(
        session, course_id=course.id, document_id=document.id, syllabus_text="No useful info here.", claude_client=client
    )
    assert facts == []


def test_response_wrapped_in_markdown_fence_is_handled(session):
    seed_default_sources(session)
    course, document = _course_and_document(session)
    client = FakeClaudeClient('```json\n[{"subject": "Exam 1 date", "value": "October 14"}]\n```')

    facts = extract_syllabus_facts(
        session, course_id=course.id, document_id=document.id, syllabus_text="...", claude_client=client
    )
    assert len(facts) == 1


def test_invalid_json_raises_clear_error(session):
    seed_default_sources(session)
    course, document = _course_and_document(session)
    client = FakeClaudeClient("this is not json at all")

    with pytest.raises(ExtractionError, match="valid JSON"):
        extract_syllabus_facts(
            session, course_id=course.id, document_id=document.id, syllabus_text="...", claude_client=client
        )


def test_non_array_json_raises_clear_error(session):
    seed_default_sources(session)
    course, document = _course_and_document(session)
    client = FakeClaudeClient('{"subject": "Exam 1 date", "value": "October 14"}')

    with pytest.raises(ExtractionError, match="JSON array"):
        extract_syllabus_facts(
            session, course_id=course.id, document_id=document.id, syllabus_text="...", claude_client=client
        )


def test_malformed_item_raises_clear_error(session):
    seed_default_sources(session)
    course, document = _course_and_document(session)
    client = FakeClaudeClient('[{"subject": "Exam 1 date"}]')  # missing "value"

    with pytest.raises(ExtractionError, match="Malformed"):
        extract_syllabus_facts(
            session, course_id=course.id, document_id=document.id, syllabus_text="...", claude_client=client
        )


def test_prompt_includes_the_actual_syllabus_text(session):
    seed_default_sources(session)
    course, document = _course_and_document(session)
    client = FakeClaudeClient("[]")

    extract_syllabus_facts(
        session,
        course_id=course.id,
        document_id=document.id,
        syllabus_text="UNIQUE_MARKER_TEXT_12345",
        claude_client=client,
    )
    assert "UNIQUE_MARKER_TEXT_12345" in client.last_prompt
