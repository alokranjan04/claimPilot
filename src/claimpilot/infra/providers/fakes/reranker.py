"""Fake reranker — identity pass-through that preserves original ordering."""

from __future__ import annotations

from claimpilot.infra.interfaces import SearchHit


class FakeReranker:
    """No-op reranker that returns hits unchanged (truncated to *top_k*).

    Useful for offline tests where reranking quality is irrelevant.
    """

    async def rerank(
        self,
        query: str,
        hits: list[SearchHit],
        *,
        top_k: int = 5,
    ) -> list[SearchHit]:
        return hits[:top_k]
