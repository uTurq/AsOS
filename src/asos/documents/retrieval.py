"""
Retrieval.

Brute-force cosine similarity over document_chunks — deliberately NOT
a vector index (sqlite-vec, Chroma, etc.). For one user's single-
semester corpus (a few dozen documents, a few thousand chunks at
most), a Python loop over rows already in memory is fast enough and
far simpler than standing up a vector index. Revisit only if a real
corpus size demonstrates this is actually too slow — don't pre-
optimize for a scale this app will never see. See PROJECT.md's open
decisions for the vector-index question this deliberately defers.
"""

from __future__ import annotations

import dataclasses

from sqlalchemy import select
from sqlalchemy.orm import Session

from asos.db.models import Document, DocumentChunk
from asos.documents.embeddings import EmbeddingProvider, cosine_similarity, deserialize_embedding


@dataclasses.dataclass
class ScoredChunk:
    chunk: DocumentChunk
    document: Document
    score: float


def search_chunks(
    session: Session,
    *,
    query: str,
    embedding_provider: EmbeddingProvider,
    course_id: int | None = None,
    document_ids: list[int] | None = None,
    top_k: int = 5,
) -> list[ScoredChunk]:
    """Returns the top_k chunks most similar to `query`, optionally
    restricted to a course or an explicit set of document ids (e.g. the
    documents linked to a specific assessment)."""
    stmt = select(DocumentChunk, Document).join(Document, DocumentChunk.document_id == Document.id)
    if course_id is not None:
        stmt = stmt.where(Document.course_id == course_id)
    if document_ids is not None:
        if not document_ids:
            return []
        stmt = stmt.where(Document.id.in_(document_ids))

    rows = session.execute(stmt).all()
    if not rows:
        return []

    query_vector = embedding_provider.embed([query])[0]

    scored = []
    for chunk, document in rows:
        if chunk.embedding is None:
            continue
        chunk_vector = deserialize_embedding(chunk.embedding)
        score = cosine_similarity(query_vector, chunk_vector)
        scored.append(ScoredChunk(chunk=chunk, document=document, score=score))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top_k]
