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
| M6 — MCP tool servers | ✅ Done | 151 |
| M7 — Eval harness + CI gate | ✅ Done | 169 |
| M8 — API + queue + checkpointing | ✅ Done | 182 |
| M9 — Observability | ✅ Done | 205 |
| M10–M11 — Azure providers + deploy | 🚧 Next | |

> The arc: **M0–M2 built the safe, testable foundation · M3 made it flow · M4 gave it grounded knowledge · M5 makes the decisions real · M6 added enterprise tool integration · M7 gates every change on measurable quality · M8 exposes it all as a production-grade async REST API · M9 makes every claim traceable with spans, structured logs, and cost accounting.**

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

## M6 — MCP tool servers ✅
Four MCP tool servers (`policy_db`, `claims_history`, `fraud_signals`, `regs`) with typed schemas, input validation, and **authz enforced at the boundary** (`_check_auth`, not the data model — the model never holds credentials). Relevant agents call tools through the interface (fraud/risk → claims_history + fraud_signals; compliance → regs with derived jurisdiction), and every tool call is recorded in the `trace`.

**Why it matters:** enterprise integrations become reusable, standards-based, and observable — and tool-call correctness is now something the eval harness can score. (151 tests)

---

## M7 — Evaluation harness + CI gate ✅
A 10-case golden dataset (`evals/golden/cases.json`) spanning every routing path — auto_approved (3), auto_denied (1), and escalated (6) — covering low-confidence, high-amount, high-fraud-risk, compliance-failure, multi-threshold, zero-payable, and insufficient-RAG-context scenarios. Each case has scripted LLM responses and declared expected outcomes. `evals/metrics.py` defines five gated metrics: **decision accuracy**, **escalation precision/recall**, **citation faithfulness** (all citation clause_ids must exist in the retrieved policy context — no hallucinations), and **tool-call correctness** (expected MCP tool calls must appear in the trace). `evals/run_evals.py` runs all cases end-to-end, emits a human-readable scorecard, and exits 1 if any gate threshold is breached. The CI workflow (`ci.yml`) runs `make eval` on every PR — a gate that blocks merge on metric regression.

**Scorecard (fakes, offline):** 10/10 cases pass · decision accuracy 100% · escalation P/R 100%/100% · citation faithfulness 100% · tool-call accuracy 100% · p50 latency ≈ 5 ms/claim. (169 tests total)

**Why it matters:** *"Every change is gated on these numbers"* — this is the interview closer. The scorecard is the evidence that the system produces grounded, correct decisions without hallucinated citations.

## M8 — FastAPI surface + async worker + human-in-the-loop ✅
A full REST API (`src/claimpilot/api/`) built on FastAPI with a background worker that consumes a `Queue`, runs the LangGraph graph, and persists results via the `Checkpointer` — all through the same DI interfaces used by the rest of the system (PROVIDER=fake for tests).

**Endpoints:**
- `POST /v1/claims` — accept and enqueue a claim, return `claim_id` and status `pending` immediately (202).
- `GET /v1/claims/{id}` — poll status, disposition, all agent outputs (coverage, risk, settlement, compliance), full trace, and errors.
- `GET /v1/claims/{id}/stream` — SSE stream of `StepTrace` events as each graph node completes; replays stored events if processing finished before the client connected.
- `POST /v1/claims/{id}/decision` — human adjudicator approves/denies an escalated claim, transitioning it to `completed`; 409 if not in escalated status.
- `GET /v1/evals/latest` — lazily runs the full eval harness and returns the gate-passing scorecard.
- `GET /healthz` / `GET /readyz` — liveness and readiness probes.

**Architecture details:** `ClaimStore` wraps the `Checkpointer` with typed `ClaimRecord` snapshots; `EventBus` routes `StepTrace | None` sentinels via per-claim `asyncio.Queue`; the worker publishes events via `graph.astream(stream_mode="values")` and sets `status=escalated` when disposition is escalated. Money amounts are serialized as strings (Pydantic v2 Decimal→JSON). The ASGI lifespan wires DI providers at startup and cancels the worker cleanly at shutdown.

**E2e tests:** 13 scenarios in `tests/test_api_e2e.py` using `httpx.AsyncClient` + `ASGITransport` with a hand-rolled ASGI lifespan manager (no extra dependencies): submit→process→fetch auto-approved, decimal serialization, escalation→approve, escalation→deny, decision-on-non-escalated 409, SSE step+done events, SSE error event for unknown claim, evals gate.

**Gate (182 tests, all green):** `ruff` clean · `mypy --strict` clean · 182/182 tests pass offline.

---

## M9 — Observability + cost meter ✅
Three modules in `src/claimpilot/observability/` wired across the entire system:

**`observability/tracer.py`** — OTel-compatible span model. `SpanData` (Pydantic, with UUID span_id/trace_id, claim_id, start/end times, duration_ms, attributes, status_ok) and a `SpanExporter` protocol with `NoOpSpanExporter` (default, zero overhead) and `InMemorySpanExporter` (test assertions). The `build_graph()` function now accepts an optional `span_exporter` parameter. Every graph node emits a span: agent nodes via the enhanced `_safe()` wrapper (async, catches errors), routing/terminal nodes via the new `_timed()` wrapper (sync). Both wrappers measure wall-clock latency and **patch `StepTrace.latency_ms`** on the returned trace entry — so the audit trail now carries real latency per node.

**`observability/logging.py`** — structlog-based structured JSON logging. A `_drop_pii()` processor strips sensitive fields (`fnol_text`, `messages`, `prompt`, `raw_input`, `response_text`, `parties`, `claimant`, `name`) before any record reaches the output sink. `get_logger(claim_id)` binds `claim_id` as a context variable so every record is traceable without the caller passing it. `configure_logging()` is idempotent and supports JSON (prod) or console (dev) output. The worker now logs `claim_processing_started` and `claim_processing_completed` with disposition and cost, but never with PII.

**`observability/cost_meter.py`** — `ClaimCostSummary` (per-claim cost and latency aggregation) and `compute_cost_summary(claim_id, trace)` which sums `StepTrace.cost_usd` and `latency_ms` per node. Cost uses a GPT-4o pricing proxy ($5/1M input, $15/1M output); fake LLM produces `Decimal(0)` (no real calls). Decimal values serialise as strings in JSON mode. The `ClaimRecord` now stores `cost_summary_data` and exposes `to_cost_summary()`. `GET /v1/claims/{id}` includes `cost_summary` in the response.

**Eval scorecard**: `Scorecard.avg_cost_usd` computed from token counts in `compute_scorecard()`. The `run_evals.py` printer shows `Avg cost (est.)` per case. Real providers will populate non-zero costs via the `usage` field in LLM responses.

**Tests** (`tests/test_observability.py`): 23 new tests — tracer unit tests (no-op, in-memory, clear, names, unique IDs, protocol conformance), graph integration tests (every node in the auto-approve path emits a span, claim_id on every span, real latency > 0, `StepTrace.latency_ms` populated after `ainvoke`), cost meter unit tests (empty trace, single step, multi-step sums, repeated-node accumulation, Decimal serialisation), and logging tests (PII filter drops all 8 keys, preserves non-PII, `get_logger` binds claim_id, no PII in captured records).

**Gate (205 tests, all green):** `ruff` clean · `mypy --strict` clean (57 source files) · 205/205 tests pass offline in 2.3 s.

---

## What's next
- **M10–M11** Azure providers (Azure OpenAI, AI Search, Document Intelligence, Container Apps, Azure Monitor OTel exporter) + deploy.
- **Demo cut line:** M9 is now the cut line — every claim produces a complete, traceable, cost-accounted audit record; M10–M11 wire in the production Azure backend.
