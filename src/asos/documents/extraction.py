"""
Structured fact extraction from syllabus text via Claude.

One Claude call per syllabus (not per query) — this is the "sparse,
one-time Claude pass" from the locked design, not something invoked on
every retrieval. The extracted facts are recorded through
asos.facts.authority.record_fact with source_type=SYLLABUS,
document_id set for full provenance, so they can later participate in
conflict resolution against Canvas-sourced facts.

The Claude client is injectable (a Protocol, same DI pattern used for
keyring and the Canvas HTTP session) so this is fully testable without
a real API key or network call. See PROJECT.md: a real end-to-end call
against the live Anthropic API has NOT been made from this sandbox —
that needs the user's own anthropic_api_key and explicit awareness
that it's a real, billed request.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

from sqlalchemy.orm import Session

from asos.db.enums import FactConfidence, FactExplicitness, SourceType
from asos.facts.authority import record_fact

logger = logging.getLogger("asos.documents.extraction")

EXTRACTION_PROMPT_TEMPLATE = """You are extracting structured facts from a course syllabus.

Read the syllabus text below and extract ONLY facts that are explicitly
and unambiguously stated in the text. Do not infer, guess, or fill in
anything the text doesn't directly say. If a category isn't mentioned,
omit it entirely — do not invent a value.

Extract these categories where present:
- exam dates (subject like "Exam 1 date", value like the stated date)
- grading breakdown (subject like "Grading breakdown", value like "Exams 60%, Homework 25%, Participation 15%")
- late policy (subject "Late policy", value as stated)

Respond with ONLY a JSON array, no other text, no markdown code fences.
Each element: {{"subject": "...", "value": "..."}}
If nothing qualifies, respond with an empty array: []

Syllabus text:
---
{text}
---
"""


class ClaudeClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class ExtractionError(RuntimeError):
    pass


def _build_prompt(text: str) -> str:
    return EXTRACTION_PROMPT_TEMPLATE.format(text=text)


def _parse_extraction_response(raw: str) -> list[dict]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json") :]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Claude's extraction response wasn't valid JSON: {exc}") from None

    if not isinstance(parsed, list):
        raise ExtractionError(f"Expected a JSON array from extraction, got {type(parsed).__name__}")

    for item in parsed:
        if not isinstance(item, dict) or "subject" not in item or "value" not in item:
            raise ExtractionError(f"Malformed extraction item (needs subject+value): {item!r}")

    return parsed


def extract_syllabus_facts(
    session: Session,
    *,
    course_id: int | None,
    document_id: int,
    syllabus_text: str,
    claude_client: ClaudeClient,
) -> list:
    """Runs one Claude extraction pass over syllabus text and records
    each extracted fact via record_fact. Facts extracted this way use
    MEDIUM confidence by default (not HIGH) despite being marked
    explicit_statement — the underlying syllabus statement is explicit,
    but the extraction itself is an LLM parse that could still
    misread or hallucinate, so confidence is intentionally more
    conservative than a human directly transcribing the same text."""
    prompt = _build_prompt(syllabus_text)
    raw_response = claude_client.complete(prompt)
    extracted_items = _parse_extraction_response(raw_response)

    facts = []
    for item in extracted_items:
        fact = record_fact(
            session,
            course_id=course_id,
            subject=item["subject"],
            value=item["value"],
            source_type=SourceType.SYLLABUS,
            explicitness=FactExplicitness.EXPLICIT_STATEMENT,
            confidence=FactConfidence.MEDIUM,
            document_id=document_id,
        )
        facts.append(fact)

    logger.info("extracted %d fact(s) from syllabus document_id=%s", len(facts), document_id)
    return facts
