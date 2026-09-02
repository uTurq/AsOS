from __future__ import annotations

from asos.documents.chunking import chunk_units
from asos.documents.parsing import ParsedUnit


def test_small_document_becomes_one_chunk():
    units = [ParsedUnit(label="page 1", text="This is a short syllabus paragraph about grading.")]
    chunks = chunk_units(units)
    assert len(chunks) == 1
    assert "grading" in chunks[0].text
    assert chunks[0].label == "page 1"


def test_long_document_splits_into_multiple_chunks():
    long_paragraph = " ".join(f"word{i}" for i in range(1200))
    units = [ParsedUnit(label="page 1", text=long_paragraph)]
    chunks = chunk_units(units, target_words=400, max_words=500)
    assert len(chunks) >= 3
    # No chunk should exceed max_words by much (a single run of words
    # with no paragraph breaks still gets packed up to the target).
    for chunk in chunks:
        assert len(chunk.text.split()) <= 500


def test_oversized_single_paragraph_is_hard_split_not_truncated():
    huge_paragraph = " ".join(f"word{i}" for i in range(2000))
    units = [ParsedUnit(label="page 1", text=huge_paragraph)]
    chunks = chunk_units(units, target_words=400, max_words=500)
    total_words_out = sum(len(c.text.split()) for c in chunks)
    assert total_words_out == 2000  # nothing lost
    assert len(chunks) == 5  # 2000 / 400 target size
    for chunk in chunks:
        assert len(chunk.text.split()) <= 500


def test_chunks_are_indexed_sequentially():
    units = [ParsedUnit(label=f"page {i}", text="word " * 450) for i in range(3)]
    chunks = chunk_units(units, target_words=400, max_words=500)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_empty_units_produce_no_chunks():
    assert chunk_units([]) == []
    assert chunk_units([ParsedUnit(label=None, text="   ")]) == []


def test_multiple_units_preserve_label_of_chunk_start():
    units = [
        ParsedUnit(label="slide 1", text="Intro to mitosis."),
        ParsedUnit(label="slide 2", text="Phases: prophase, metaphase, anaphase, telophase."),
    ]
    chunks = chunk_units(units, target_words=400, max_words=500)
    assert len(chunks) == 1  # both slides are small enough to merge into one chunk
    assert chunks[0].label == "slide 1"
