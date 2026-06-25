"""RAG pipeline — ingest, hybrid retrieve, rerank, and grounding.

All provider interaction goes through the injected ``Embedder``,
``VectorStore``, and ``Reranker`` interfaces.  No cloud imports.
"""

from __future__ import annotations

from claimpilot.infra.interfaces import Embedder, Reranker, SearchHit, VectorRecord, VectorStore
from claimpilot.infra.settings import Settings
from claimpilot.models.common import Citation
from claimpilot.rag.bm25 import BM25Index
from claimpilot.rag.chunker import Chunk, chunk_document
from claimpilot.rag.models import (
    IngestReport,
    RagNotReadyError,
    RetrievalFilter,
    RetrievalResult,
    RetrievedChunk,
    SourceDoc,
)


class RagPipeline:
    """End-to-end RAG: ingest → hybrid retrieve → rerank → ground."""

    def __init__(
        self,
        *,
        embedder: Embedder,
        vector_store: VectorStore,
        reranker: Reranker,
        settings: Settings | None = None,
    ) -> None:
        self._embedder = embedder
        self._vs = vector_store
        self._reranker = reranker
        s = settings or Settings()
        self._k = s.rag_k
        self._dense_w = s.rag_dense_weight
        self._lexical_w = s.rag_lexical_weight
        self._tau = s.rag_tau_sufficient
        self._chunk_tokens = s.rag_chunk_tokens
        self._chunk_overlap = s.rag_chunk_overlap

        self._bm25 = BM25Index()
        self._chunks: dict[str, Chunk] = {}
        self._ingested = False

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    async def ingest(self, corpus: list[SourceDoc]) -> IngestReport:
        """Chunk, embed, and index *corpus* for retrieval."""
        all_chunks: list[Chunk] = []
        for doc in corpus:
            all_chunks.extend(
                chunk_document(doc, max_tokens=self._chunk_tokens, overlap=self._chunk_overlap)
            )

        # Store chunk lookup + BM25 index.
        for ch in all_chunks:
            self._chunks[ch.clause_id] = ch
            self._bm25.add(ch.clause_id, ch.text)

        # Embed and upsert into the vector store.
        texts = [ch.text for ch in all_chunks]
        if texts:
            embeddings = await self._embedder.embed(texts)
            records = [
                VectorRecord(
                    id=ch.clause_id,
                    text=ch.text,
                    embedding=emb,
                    metadata={
                        "doc_id": ch.doc_id,
                        "title": ch.title,
                        "clause_id": ch.clause_id,
                        **ch.metadata,
                    },
                )
                for ch, emb in zip(all_chunks, embeddings, strict=True)
            ]
            await self._vs.upsert(records)

        self._ingested = True
        return IngestReport(docs_ingested=len(corpus), chunks_created=len(all_chunks))

    # ------------------------------------------------------------------
    # Retrieve
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        *,
        k: int | None = None,
        filters: RetrievalFilter | None = None,
    ) -> RetrievalResult:
        """Hybrid retrieve, rerank, and apply grounding contract."""
        if not self._ingested:
            raise RagNotReadyError("Pipeline has not ingested a corpus yet.")

        top_k = k or self._k
        filter_meta = filters.metadata if filters else None

        # 1. Dense retrieval.
        [query_emb] = await self._embedder.embed([query])
        dense_hits = await self._vs.search(query_emb, top_k=top_k * 3, filter_metadata=filter_meta)

        # 2. Lexical (BM25) retrieval.
        bm25_results = self._bm25.search(query, top_k=top_k * 3)

        # 3. Reciprocal-rank fusion + de-duplication by clause_id.
        fused = _reciprocal_rank_fusion(
            dense_hits=dense_hits,
            bm25_results=bm25_results,
            dense_weight=self._dense_w,
            lexical_weight=self._lexical_w,
        )

        # Convert to SearchHit for the reranker.
        rerank_input: list[SearchHit] = []
        for clause_id, score in fused[: top_k * 2]:
            ch = self._chunks.get(clause_id)
            if ch is None:
                continue  # pragma: no cover
            rerank_input.append(
                SearchHit(
                    id=clause_id,
                    text=ch.text,
                    score=score,
                    metadata={"doc_id": ch.doc_id, "title": ch.title, "clause_id": clause_id},
                )
            )

        # 4. Rerank.
        reranked = await self._reranker.rerank(query, rerank_input, top_k=top_k)

        # 5. Build grounded result.
        chunks: list[RetrievedChunk] = []
        for hit in reranked:
            ch = self._chunks.get(hit.id)
            if ch is None:
                continue  # pragma: no cover
            snippet = ch.text[:200]
            chunks.append(
                RetrievedChunk(
                    citation=Citation(
                        clause_id=hit.id,
                        document=ch.title,
                        snippet=snippet,
                    ),
                    text=ch.text,
                    score=hit.score,
                )
            )

        best_score = max((c.score for c in chunks), default=0.0)
        sufficient = bool(chunks) and best_score >= self._tau

        return RetrievalResult(chunks=chunks, sufficient=sufficient)


# ---------------------------------------------------------------------------
# Reciprocal-rank fusion
# ---------------------------------------------------------------------------

_RRF_K = 60  # standard RRF constant


def _reciprocal_rank_fusion(
    *,
    dense_hits: list[SearchHit],
    bm25_results: list[tuple[str, float]],
    dense_weight: float,
    lexical_weight: float,
) -> list[tuple[str, float]]:
    """Fuse dense + BM25 results via weighted reciprocal-rank fusion.

    Returns ``(clause_id, fused_score)`` sorted descending by score,
    with stable secondary sort by clause_id for determinism on ties.
    De-duplicates by clause_id automatically.
    """
    scores: dict[str, float] = {}

    for rank, hit in enumerate(dense_hits, start=1):
        scores[hit.id] = scores.get(hit.id, 0.0) + dense_weight / (rank + _RRF_K)

    for rank, (clause_id, _bm25_score) in enumerate(bm25_results, start=1):
        scores[clause_id] = scores.get(clause_id, 0.0) + lexical_weight / (rank + _RRF_K)

    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))
