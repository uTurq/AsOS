"""
Embedding provider interface.

IMPORTANT — read before changing the default provider:
This module defines the interface (`EmbeddingProvider`) that the rest
of the ingestion/retrieval pipeline depends on, and ships exactly one
implementation: `HashingEmbeddingProvider`, a deterministic,
dependency-free placeholder. It is NOT a real semantic embedding model
— it captures word overlap, not meaning, so retrieval quality with it
is mediocre at best. It exists so the pipeline (chunking -> embedding
-> storage -> cosine-similarity retrieval) can be built and correctly
tested end-to-end right now, without a real model dependency this
sandbox can't download (see PROJECT.md: no network access to a model
hub from here).

Swapping in a real local model (e.g. a small sentence-transformers
model) later should mean writing one more class that satisfies
EmbeddingProvider and changing exactly one line where it's
constructed — nothing else in this module, or in
asos.documents.retrieval, should need to change. That real choice
needs to be made and latency-tested on the actual target machine
(Windows, CPU-only, no GPU), not assumed here.
"""

from __future__ import annotations

import array
import hashlib
import math
from typing import Protocol

DEFAULT_DIMENSIONS = 256


class EmbeddingProvider(Protocol):
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbeddingProvider:
    """Deterministic placeholder embedding: a normalized hashed
    bag-of-words vector. No model download, no ML dependency, fully
    reproducible — good enough to validate the pipeline's plumbing, not
    good enough for real semantic retrieval quality. See module
    docstring."""

    def __init__(self, dimensions: int = DEFAULT_DIMENSIONS):
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in text.lower().split():
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


def serialize_embedding(vector: list[float]) -> bytes:
    return array.array("f", vector).tobytes()


def deserialize_embedding(data: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(data)
    return list(a)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)
