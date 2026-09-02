"""
Document ingestion: parse -> chunk -> embed -> store.

This is the pipeline a watched-folder worker or a CLI command drives.
Kept as plain functions over a SQLAlchemy session (not a class) since
there's no state to carry between calls — matches the project's
"avoid unnecessary abstraction" principle.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from asos.config import get_data_dir
from asos.db.base import _now
from asos.db.enums import DocumentSourceType
from asos.db.models import Document, DocumentChunk
from asos.documents.chunking import chunk_units
from asos.documents.embeddings import EmbeddingProvider, serialize_embedding
from asos.documents.parsing import parse_document


def _documents_storage_dir() -> Path:
    path = get_data_dir() / "documents"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ingest_document(
    session: Session,
    *,
    source_path: Path,
    course_id: int | None,
    source_type: DocumentSourceType,
    title: str | None,
    embedding_provider: EmbeddingProvider,
) -> Document:
    """Parses, chunks, embeds, and stores a document. Copies the source
    file into AsOS's own data directory first — ingestion shouldn't
    silently depend on the original file staying where it was (e.g. a
    watched Downloads folder the user later cleans up)."""
    stored_dir = _documents_storage_dir()
    stored_path = stored_dir / f"{_now().strftime('%Y%m%dT%H%M%S%f')}_{source_path.name}"
    shutil.copy2(source_path, stored_path)

    document = Document(
        course_id=course_id,
        title=title or source_path.stem,
        source_type=source_type,
        file_path=str(stored_path),
        ingested_at=_now(),
    )
    session.add(document)
    session.flush()  # assigns document.id

    units = parse_document(source_path)
    chunks = chunk_units(units)

    if chunks:
        vectors = embedding_provider.embed([c.text for c in chunks])
        for chunk, vector in zip(chunks, vectors):
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=chunk.index,
                    content=chunk.text,
                    page_or_slide=chunk.label,
                    embedding=serialize_embedding(vector),
                )
            )

    session.commit()
    return document


def get_documents_for_assessment(session: Session, assessment_id: int) -> list[Document]:
    from asos.db.models import AssessmentDocument

    stmt = (
        select(Document)
        .join(AssessmentDocument, AssessmentDocument.document_id == Document.id)
        .where(AssessmentDocument.assessment_id == assessment_id)
    )
    return list(session.execute(stmt).scalars().all())
