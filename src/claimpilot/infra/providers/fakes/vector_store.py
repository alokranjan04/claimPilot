"""Fake vector store — in-memory dict with brute-force cosine similarity."""

from __future__ import annotations

import math

from claimpilot.infra.interfaces import SearchHit, VectorRecord


class FakeVectorStore:
    """In-memory vector store backed by a plain dict.

    Similarity search uses brute-force cosine similarity — fine for
    test-sized corpora.
    """

    def __init__(self) -> None:
        self._store: dict[str, VectorRecord] = {}

    async def upsert(self, records: list[VectorRecord]) -> None:
        for rec in records:
            self._store[rec.id] = rec

    async def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        filter_metadata: dict[str, str] | None = None,
    ) -> list[SearchHit]:
        candidates: list[tuple[float, VectorRecord]] = []
        for rec in self._store.values():
            if filter_metadata and not all(
                rec.metadata.get(k) == v for k, v in filter_metadata.items()
            ):
                continue
            score = _cosine_similarity(query_embedding, rec.embedding)
            candidates.append((score, rec))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [
            SearchHit(id=rec.id, text=rec.text, score=score, metadata=rec.metadata)
            for score, rec in candidates[:top_k]
        ]

    async def delete(self, ids: list[str]) -> None:
        for id_ in ids:
            self._store.pop(id_, None)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
