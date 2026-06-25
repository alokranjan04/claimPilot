# Component Spec — RAG Pipeline (M4)

**Drives:** M4 · **Code:** `src/claimpilot/rag/` · **Depends on:** `Embedder`, `VectorStore` interfaces (M2); `Citation`, `PolicyContext` models (M1).

## Purpose
Retrieve the policy/regulatory passages an agent needs to ground a decision, and return them with citations. The pipeline must make grounding *enforceable*: every retrieved fact is traceable to a source, and when retrieval is too weak to answer, the pipeline says so rather than guessing.

## Inputs / Outputs (typed)
```
ingest(corpus: list[SourceDoc]) -> IngestReport         # one-time / incremental
retrieve(query: str, k: int, filters: RetrievalFilter | None) -> RetrievalResult
```
- `SourceDoc`: `{doc_id, title, text, metadata: {jurisdiction, policy_type, section_path}}`
- `RetrievalResult`: `{chunks: list[RetrievedChunk], sufficient: bool}`
- `RetrievedChunk`: `{citation: Citation, text, score: float}` — `Citation` is the M1 model (`clause_id`, `document`, `snippet`).
- `PolicyContext` (M1) is assembled from a `RetrievalResult` for the Policy-Retrieval agent.

## Behavior
1. **Chunking** — split along document structure (sections/clauses via `section_path`), not fixed windows. Target ~300–600 tokens with small overlap. Each chunk keeps a stable `clause_id` derived from `doc_id + section_path`.
2. **Embedding** — call the injected `Embedder` (fake in tests, Azure OpenAI `text-embedding-3-large` in prod). Never import a provider directly.
3. **Hybrid retrieval** — combine lexical (BM25-style keyword) + dense (vector) candidates; fuse with weighted reciprocal-rank fusion. Default weights: `dense=0.6, lexical=0.4` (config-overridable). Lexical matters for exact tokens like clause IDs and money terms.
4. **Rerank** — pass fused candidates through the `Reranker` interface (no-op/identity in fakes; Azure AI Search semantic ranker in prod) to produce the final top-`k`.
5. **Grounding contract** — return chunks with citations only. Compute `sufficient = (best_score >= τ_sufficient) and (len(chunks) > 0)`. The consuming agent must treat `sufficient = False` as "insufficient context → escalate."
6. **Determinism** — given the same corpus + query + fake embedder, results are identical run to run.

## Config (settings)
`rag.k=5`, `rag.dense_weight=0.6`, `rag.lexical_weight=0.4`, `rag.tau_sufficient=0.35`, `rag.chunk_tokens=450`, `rag.chunk_overlap=50`. All overridable by env.

## Edge cases (must handle explicitly)
- **Empty / no-match query** → `sufficient=False`, `chunks=[]`; never fabricate a citation.
- **Corpus not ingested** → raise a typed `RagNotReadyError` (caught by graph error_handler), not a bare exception.
- **Duplicate chunks across lexical+dense** → de-duplicate by `clause_id` before rerank.
- **Very long source doc** → chunk without dropping tail content; assert total coverage in a test.
- **Ambiguous query spanning multiple policies** → return chunks from each with distinct `document` values; do not silently prefer one.
- **Score ties** → stable secondary sort by `clause_id` for determinism.

## Acceptance tests
- [ ] Ingest a bundled synthetic corpus fixture; chunk count and coverage assertions pass (no lost text).
- [ ] `retrieve` returns chunks each carrying a valid `Citation`; no chunk lacks a source.
- [ ] Grounding: a query with no relevant content yields `sufficient=False` and empty `chunks`.
- [ ] Hybrid beats pure-dense on an exact-clause-ID query (lexical recall test).
- [ ] De-duplication: a query that matches the same clause lexically and densely returns it once.
- [ ] Determinism: identical results across two runs with the fake embedder.
- [ ] `RagNotReadyError` raised when retrieving before ingest.
- [ ] mypy strict clean; ruff clean.

## Out of scope for M4 (later)
GraphRAG / multi-hop (optional M13); real Azure AI Search wiring (M10); incremental re-index scheduling (note the interface, stub the impl).
