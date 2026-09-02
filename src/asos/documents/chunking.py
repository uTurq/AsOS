"""
Chunking.

Splits parsed document units (asos.documents.parsing.ParsedUnit) into
chunks sized for embedding/retrieval. Word count is used as a cheap
stand-in for token count — good enough for sizing chunks sensibly
without pulling in a real tokenizer as a dependency; if retrieval
quality ever demands token-exact sizing, swap the counting function
here without touching callers.
"""

from __future__ import annotations

import dataclasses

from asos.documents.parsing import ParsedUnit

DEFAULT_TARGET_WORDS = 400
DEFAULT_MAX_WORDS = 500


@dataclasses.dataclass
class Chunk:
    index: int
    label: str | None
    text: str


def chunk_units(
    units: list[ParsedUnit],
    *,
    target_words: int = DEFAULT_TARGET_WORDS,
    max_words: int = DEFAULT_MAX_WORDS,
) -> list[Chunk]:
    """Greedily packs paragraphs from consecutive units into chunks of
    roughly `target_words`, never exceeding `max_words` — a paragraph
    longer than `max_words` on its own is hard-split into
    `target_words`-sized pieces rather than either truncated (losing
    content) or left as one unboundedly large chunk (bad for
    embedding/retrieval quality)."""
    chunks: list[Chunk] = []
    current_words: list[str] = []
    current_label: str | None = None

    def _flush():
        nonlocal current_words, current_label
        if current_words:
            chunks.append(Chunk(index=len(chunks), label=current_label, text=" ".join(current_words)))
        current_words = []
        current_label = None

    for unit in units:
        for paragraph in unit.text.split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            paragraph_words = paragraph.split()

            if current_label is None:
                current_label = unit.label

            if len(paragraph_words) > max_words:
                # A single paragraph longer than max_words on its own:
                # flush whatever's pending, then hard-split this
                # paragraph into target_words-sized pieces. This still
                # loses nothing (every word ends up in some chunk) — it
                # just means the paragraph itself becomes several
                # sequential chunks instead of one unbounded one.
                _flush()
                current_label = unit.label
                for i in range(0, len(paragraph_words), target_words):
                    piece = paragraph_words[i : i + target_words]
                    chunks.append(Chunk(index=len(chunks), label=current_label, text=" ".join(piece)))
                continue

            if len(current_words) + len(paragraph_words) > max_words and current_words:
                _flush()
                current_label = unit.label

            current_words.extend(paragraph_words)

            if len(current_words) >= target_words:
                _flush()

    _flush()
    return chunks
