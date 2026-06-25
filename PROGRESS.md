# ClaimPilot — Build Progress

Spec-driven, milestone by milestone. Everything runs **offline on deterministic fakes** — no cloud or API keys needed to build, test, or demo. See `docs/BUILD_PLAN.md` for the full roadmap and `docs/specs/` for the source-of-truth specs.

| Milestone | Status | Tests |
|---|---|---|
| M0 — Foundation & quality gate | ✅ Done | 2 |
| M1 — Domain models | ✅ Done | 44 |
| M2 — Provider interfaces + fakes | ✅ Done | 91 |
| M3 — LangGraph orchestration | ✅ Done | — |
| M4 — RAG pipeline | ✅ Done | 98 |
| M5 — Real agents + graph wiring (RAG→coverage) | ✅ Done | 126 |
| M6 — MCP tool servers | 🚧 Next | |
| M7 — Eval harness + CI gate | ⬜ Planned | |
| M8 — API + queue + checkpointing | ⬜ Planned | |
| M9 — Observability | ⬜ Planned | |
| M10–M11 — Azure providers + deploy | ⬜ Planned | |

> The arc: **M0–M2 built the safe, testable foundation · M3 made it flow · M4 gave it grounded knowledge · M5 makes the decisions real.**

---

## M0 — Foundation & quality gate ✅
Set up the empty package structure, a `/healthz` endpoint to prove the app boots, and the tooling that polices everything after: `uv`, `ruff` (style), `mypy --strict` (type correctness), `pytest`, a `Makefile` gate, pre-commit hooks, and a CI workflow.

**Why it matters:** the workshop and the quality inspectors come before any feature, so the codebase stays clean as it grows. (2 tests)

## M1 — Domain models (the typed boundaries) ✅
Defined every data shape in Pydantic v2: `RawClaim`, `ClaimFacts`, `Citation`, `PolicyContext`, `CoverageOpinion`, `RiskAssessment`, `SettlementProposal`, `ComplianceVerdict`, `StepTrace`, `AgentError`, and `ClaimState`. Validators encode business rules as types: money is always `Decimal`, a coverage decision **cannot exist** without citations, payable can't exceed the limit, failed compliance must list violations, confidence is bounded to [0, 1].

**Why it matters:** invalid states become impossible to construct — the type system enforces grounding and business rules. (44 tests)

## M2 — Provider interfaces + fakes (the portability spine) ✅
Seven typed interfaces — `LLMClient`, `Embedder`, `VectorStore`, `DocExtractor`, `Queue`, `Checkpointer`, `Reranker` — with deterministic in-memory fakes behind them, a `PROVIDER` setting, and a DI factory returning a frozen `ProviderSet`. The `FakeLLMClient` is scriptable (FIFO scripted responses → response-map → hash fallback) so agent tests can force specific outcomes. ADR 002 records the decision to keep our `Checkpointer` canonical and adapt it to LangGraph's saver.

**Why it matters:** the whole system runs offline with no cloud or keys, and swapping to Azure later is a config change, not a rewrite. (91 tests total)

## M3 — LangGraph orchestration skeleton ✅
Wired the full claim-flow graph — intake → policy retrieval → coverage → fraud/risk → settlement → compliance → **router** → auto-settle *or* escalate — with stub agents, a conditional router driven by settings thresholds (confidence · amount · risk · compliance), an `error_handler` node, and the `LangGraphCheckpointAdapter` for pause/resume. `GraphState` uses `operator.add` reducers so every node **appends** a `StepTrace`. Integration tests cover the auto-approve, escalate, and error paths.

**Why it matters:** first point the system behaves end to end — a synthetic claim flows start-to-finish down both branches, with a full audit trace.

## M4 — RAG pipeline (grounded retrieval) ✅
Structure-aware chunking (stable `clause_id = {doc_id}:{section_path}`), an in-memory BM25 index whose tokenizer preserves clause tokens like `§1.2`, hybrid retrieval with weighted reciprocal-rank fusion (dense 0.6 / lexical 0.4), de-duplication by `clause_id`, reranking via the `Reranker` interface, and the **grounding contract**: retrieval returns cited chunks plus a `sufficient` flag, and a weak query yields "insufficient context" instead of a guessed answer. Backed by a 3-doc synthetic corpus fixture; all 8 acceptance tests pass.

**Why it matters:** answers are traceable to sources, and "insufficient context → escalate" is the safety mechanism the coverage agent depends on. (98 tests total)

## M5 — Real agents + graph wiring ✅
All four agents built on the coverage reference pattern (pure async, injected `LLMClient`, structured output, typed errors): **coverage** (insufficient-context guard, citation stripping, confidence cap), **fraud/risk** (score clamp), **settlement** (short-circuits on `denied`, clamps payable ≤ limit), **compliance** (synthesizes a violation when `passed=False` to guard the validator). Stub nodes replaced with real agents via injected closures; a `_safe()` wrapper turns agent errors into `AgentError` in state and routes to escalation. The **real M4 RAG pipeline is wired into `policy_retrieval`** — `retrieve()` → `PolicyContext` (citations + `sufficient`) — so the coverage grounding guard fires on real retrieval. End-to-end integration tests cover auto-approve, escalate, and a genuine insufficient-context escalation.

**Why it matters:** this is a working adjudication engine — a claim flows through real, grounded, auditable decisions and lands on the correct disposition. (126 tests)

---

## What's next
- **M6** MCP tool servers · **M7** eval harness wired as a CI gate · **M8** FastAPI + queue + checkpointing · **M9** observability · **M10–M11** Azure providers (Azure OpenAI, AI Search, Document Intelligence, Container Apps) + deploy.
- **Demo cut line:** after M7 the system is a defensible, test-gated, offline-runnable showcase; M8–M11 make it production-grade on Azure.
