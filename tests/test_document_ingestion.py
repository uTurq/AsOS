from __future__ import annotations

from asos.db.enums import DocumentSourceType
from asos.db.models import Course, DocumentChunk
from asos.documents.embeddings import HashingEmbeddingProvider
from asos.documents.ingestion import ingest_document
from asos.documents.retrieval import search_chunks


def _course(session) -> Course:
    course = Course(name="Chemistry 1010")
    session.add(course)
    session.commit()
    return course


def _make_syllabus(tmp_path):
    path = tmp_path / "syllabus.txt"
    path.write_text(
        "Exam 1 covers chapters 1 through 4, focusing on buffers and titration.\n"
        "The late policy is 10 percent off per day late.\n"
        "Grading breakdown: exams 60 percent, homework 25 percent, participation 15 percent."
    )
    return path


def test_ingest_document_creates_document_and_chunks(session, tmp_path):
    course = _course(session)
    syllabus_path = _make_syllabus(tmp_path)
    provider = HashingEmbeddingProvider(dimensions=64)

    document = ingest_document(
        session,
        source_path=syllabus_path,
        course_id=course.id,
        source_type=DocumentSourceType.SYLLABUS,
        title="Fall 2026 Syllabus",
        embedding_provider=provider,
    )

    assert document.id is not None
    assert document.title == "Fall 2026 Syllabus"
    assert document.ingested_at is not None

    chunks = session.query(DocumentChunk).filter_by(document_id=document.id).all()
    assert len(chunks) >= 1
    assert all(c.embedding is not None for c in chunks)


def test_ingest_document_copies_file_independent_of_original(session, tmp_path):
    """Ingestion must not depend on the original file staying where it
    was — the source could be a Downloads folder the user later
    empties."""
    course = _course(session)
    syllabus_path = _make_syllabus(tmp_path)
    provider = HashingEmbeddingProvider(dimensions=64)

    document = ingest_document(
        session,
        source_path=syllabus_path,
        course_id=course.id,
        source_type=DocumentSourceType.SYLLABUS,
        title=None,
        embedding_provider=provider,
    )

    syllabus_path.unlink()  # simulate the original being deleted/moved
    assert not syllabus_path.exists()

    from pathlib import Path

    assert Path(document.file_path).exists()
    assert "Exam 1" in Path(document.file_path).read_text()


def test_ingest_document_uses_filename_as_default_title(session, tmp_path):
    course = _course(session)
    syllabus_path = _make_syllabus(tmp_path)
    provider = HashingEmbeddingProvider(dimensions=64)

    document = ingest_document(
        session,
        source_path=syllabus_path,
        course_id=course.id,
        source_type=DocumentSourceType.SYLLABUS,
        title=None,
        embedding_provider=provider,
    )
    assert document.title == "syllabus"


def test_search_chunks_finds_relevant_content(session, tmp_path):
    course = _course(session)
    syllabus_path = _make_syllabus(tmp_path)
    provider = HashingEmbeddingProvider(dimensions=128)

    ingest_document(
        session,
        source_path=syllabus_path,
        course_id=course.id,
        source_type=DocumentSourceType.SYLLABUS,
        title="Syllabus",
        embedding_provider=provider,
    )

    results = search_chunks(session, query="what is the late policy", embedding_provider=provider, course_id=course.id)
    assert len(results) >= 1
    assert "late policy" in results[0].chunk.content or "late" in results[0].chunk.content.lower()


def test_search_chunks_respects_course_scoping(session, tmp_path):
    course_a = Course(name="Chemistry 1010")
    course_b = Course(name="Biology 101")
    session.add_all([course_a, course_b])
    session.commit()

    provider = HashingEmbeddingProvider(dimensions=64)

    chem_path = tmp_path / "chem.txt"
    chem_path.write_text("Buffers resist changes in pH during titration.")
    bio_path = tmp_path / "bio.txt"
    bio_path.write_text("Mitochondria are the powerhouse of the cell.")

    ingest_document(
        session,
        source_path=chem_path,
        course_id=course_a.id,
        source_type=DocumentSourceType.NOTES,
        title="Chem notes",
        embedding_provider=provider,
    )
    ingest_document(
        session,
        source_path=bio_path,
        course_id=course_b.id,
        source_type=DocumentSourceType.NOTES,
        title="Bio notes",
        embedding_provider=provider,
    )

    chem_results = search_chunks(session, query="buffers", embedding_provider=provider, course_id=course_a.id)
    assert len(chem_results) == 1
    assert "Buffers" in chem_results[0].chunk.content

    bio_results = search_chunks(session, query="buffers", embedding_provider=provider, course_id=course_b.id)
    assert len(bio_results) == 1  # only one chunk exists in course_b regardless of relevance
    assert "Mitochondria" in bio_results[0].chunk.content


def test_search_with_no_documents_returns_empty(session):
    provider = HashingEmbeddingProvider(dimensions=32)
    results = search_chunks(session, query="anything", embedding_provider=provider)
    assert results == []


def test_search_restricted_to_specific_document_ids(session, tmp_path):
    course = _course(session)
    provider = HashingEmbeddingProvider(dimensions=64)

    path_a = tmp_path / "a.txt"
    path_a.write_text("Buffers resist pH changes.")
    path_b = tmp_path / "b.txt"
    path_b.write_text("Buffers are also discussed here in more detail.")

    doc_a = ingest_document(
        session, source_path=path_a, course_id=course.id, source_type=DocumentSourceType.NOTES,
        title="A", embedding_provider=provider,
    )
    doc_b = ingest_document(
        session, source_path=path_b, course_id=course.id, source_type=DocumentSourceType.NOTES,
        title="B", embedding_provider=provider,
    )

    results = search_chunks(
        session, query="buffers", embedding_provider=provider, document_ids=[doc_a.id]
    )
    assert len(results) == 1
    assert results[0].document.id == doc_a.id

    empty_results = search_chunks(session, query="buffers", embedding_provider=provider, document_ids=[])
    assert empty_results == []
