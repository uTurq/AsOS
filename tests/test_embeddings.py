from __future__ import annotations

import math

from asos.documents.embeddings import (
    HashingEmbeddingProvider,
    cosine_similarity,
    deserialize_embedding,
    serialize_embedding,
)


def test_embedding_is_deterministic():
    provider = HashingEmbeddingProvider(dimensions=64)
    v1 = provider.embed(["buffers resist changes in pH"])[0]
    v2 = provider.embed(["buffers resist changes in pH"])[0]
    assert v1 == v2


def test_embedding_is_normalized():
    provider = HashingEmbeddingProvider(dimensions=64)
    vector = provider.embed(["some text with several distinct words here"])[0]
    norm = math.sqrt(sum(v * v for v in vector))
    assert abs(norm - 1.0) < 1e-6


def test_similar_text_more_similar_than_unrelated_text():
    provider = HashingEmbeddingProvider(dimensions=128)
    a = provider.embed(["buffers resist changes in pH during titration"])[0]
    b = provider.embed(["buffer solutions resist pH changes when titrated"])[0]
    c = provider.embed(["the mitochondria is the powerhouse of the cell"])[0]

    sim_related = cosine_similarity(a, b)
    sim_unrelated = cosine_similarity(a, c)
    assert sim_related > sim_unrelated


def test_serialize_roundtrip_preserves_values():
    provider = HashingEmbeddingProvider(dimensions=32)
    original = provider.embed(["mitochondria produce ATP"])[0]

    data = serialize_embedding(original)
    assert isinstance(data, bytes)
    restored = deserialize_embedding(data)

    assert len(restored) == len(original)
    for a, b in zip(original, restored):
        assert abs(a - b) < 1e-6  # float32 round-trip, small tolerance expected


def test_empty_text_does_not_crash():
    provider = HashingEmbeddingProvider(dimensions=16)
    vector = provider.embed([""])[0]
    assert len(vector) == 16
    assert all(v == 0.0 for v in vector)
