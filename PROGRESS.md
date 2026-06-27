# ClaimPilot — Build Progress

Spec-driven, milestone by milestone. Everything runs **offline on deterministic fakes** — no cloud or API keys needed to build, test, or demo. See `docs/BUILD_PLAN.md` for the full roadmap and `docs/specs/` for the source-of-truth specs.

> **🟢 Deployed & live on Azure Container Apps (M11):** the app is containerized and running as a public Container App, serving real GPT-5.2 adjudications end-to-end. Auto-approve path → **`auto_approved`** (coverage `covered` @ 0.90, compliance passed, $1,300 settlement, fully cited, ~$0.02/claim). Escalation paths verified live — including the **fraud/risk agent flagging a claimed-amount vs. narrative discrepancy** and escalating to human review. Production package: `docs/DEPLOYMENT_RUNBOOK.md`, `docs/PRODUCTION_ARCHITECTURE.md`, deployment-topology diagram, keyless OIDC CI/CD.
>
> **Real-model calibration note:** reasoning models report confidence non-deterministically at temperature 1; resolved by (a) recalibrating the coverage confidence rubric to measure *coverage certainty*, not file completeness, and (b) setting the auto-approve gate with margin (0.70) rather than chasing the raw number.

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
| M10 — Azure providers (live: 6 services provisioned) | ✅ Done | 240 |
| M11 — Containerise + deploy (live on Container Apps) | ✅ Done | 244 |
| M12 — AuthN/AuthZ + operator/admin UI (EasyAuth · RBAC · debug-role gated) | ✅ Done | 249 |

> The arc: **M0–M2 built the safe, testable foundation · M3 made it flow · M4 gave it grounded knowledge · M5 makes the decisions real · M6 added enterprise tool integration · M7 gates every change on measurable quality · M8 exposes it all as a production-grade async REST API · M9 makes every claim traceable with spans, structured logs, and cost accounting · M10 wires in real Azure services — zero core-code changes · M11 containerises + deploys with keyless OIDC CI/CD · M12 adds role-based auth (EasyAuth) and a Claims Console UI with Operator/Admin views.**

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

## M10 — Azure providers ✅

Seven production Azure providers behind the existing interfaces — **zero changes to core, graph, agents, rag, or api code**. `PROVIDER=azure` selects them via the DI factory; `PROVIDER=fake` is unchanged and all 205 original tests still pass.

**Provider package** (`src/claimpilot/infra/providers/azure/`):
- `AzureOpenAILLMClient` — chat completions via `openai` SDK + `azure-identity` (`DefaultAzureCredential`; no API keys)
- `AzureOpenAIEmbedder` — `text-embedding-3-small` via the same AOAI endpoint
- `AzureSearchVectorStore` — HNSW vector upsert/search via `azure-search-documents 11.x` (`VectorizedQuery`); metadata serialised as JSON string for schema flexibility
- `AzureSearchReranker` — L2 semantic ranker (`query_type="semantic"`) via the same Search service
- `AzureDocumentIntelligenceExtractor` — `prebuilt-read` model via `azure-ai-documentintelligence`; returns text + page count + avg word confidence
- `AzureServiceBusQueue` — durable at-least-once delivery with persistent peek-lock receiver and explicit `complete_message` ack
- `AzureCosmosCheckpointer` — serverless Cosmos DB SQL API; upsert/read/delete by claim_id with partition key `/id`

**Azure Monitor exporter** (`src/claimpilot/observability/azure_exporter.py`):
- `AzureMonitorSpanExporter` satisfies the `SpanExporter` protocol; calls `configure_azure_monitor()` once then emits OTel spans carrying `claim.id`, `node.name`, `duration_ms`, and error status to Application Insights.

**Settings** — 11 new optional Azure fields in `Settings` (empty-string defaults; only matter with `PROVIDER=azure`): `aoai_endpoint`, `aoai_deployment_chat`, `aoai_deployment_embedding`, `aoai_api_version`, `azure_search_endpoint`, `azure_search_index`, `azure_search_semantic_config`, `azure_docintel_endpoint`, `azure_servicebus_namespace`, `azure_servicebus_queue`, `azure_cosmos_endpoint`, `azure_cosmos_database`, `azure_cosmos_container`, `azure_monitor_connection_string`.

**IaC** (`infra/iac/main.bicep` + `parameters.json`) — Bicep baseline provisioning: Azure OpenAI (GPT-4o + text-embedding-3-small), AI Search (Standard S1 with semantic ranker), Document Intelligence (S0), Service Bus (Standard + `claims` queue), Cosmos DB (Serverless + `checkpoints` container), Log Analytics + Application Insights, Key Vault. All with `disableLocalAuth: true` and Entra ID RBAC.

**Tests** (`tests/test_azure_providers.py`): 35 new tests — all seven providers mocked via `sys.modules` injection (runs without the `azure` extra installed): LLMClient (protocol, generate, structured output, JSON-parse-error handling), Embedder (protocol, dimensions, embed, empty), VectorStore (protocol, upsert, search, delete, empty no-ops), Reranker (protocol, rerank, empty-hits), DocExtractor (protocol, extract text, confidence), Queue (protocol, enqueue, dequeue, ack, unknown-ack no-op, empty-dequeue), Checkpointer (protocol, save, load-existing, load-missing-None, delete, delete-missing-no-op), AzureMonitorSpanExporter (protocol, ok-span, error-span).

**Gate (240 tests, all green):** `ruff` clean · `mypy --strict` clean (66 source files) · 240/240 tests pass offline in 5.8 s.

**Live deployment status:** all six Azure resources provisioned and connected via `.env` — Azure OpenAI (`hindivoiceagent`, southindia), AI Search (eastus), Document Intelligence (eastus), Service Bus (southindia), Cosmos DB (southindia), Application Insights (southindia). `PROVIDER=azure` runs the full pipeline against real services. (Auth: `DefaultAzureCredential` / managed identity per the keyless design; resources have `disableLocalAuth: true`.)

---

## M11 — Containerise + deploy ✅

**Deployed and live on Azure Container Apps** at `https://claimpilot-api.victoriouswave-931a0f8e.southindia.azurecontainerapps.io/`.

**Entrypoints:**
- `worker_main.py` — standalone worker (`python -m claimpilot.api.worker_main`), runs the `run_worker` loop until SIGTERM; deployed as its own Container App with KEDA Service Bus scaling.
- `ingest_corpus.py` — one-shot corpus ingestion (`python -m claimpilot.rag.ingest_corpus`); chunks the demo policy corpus, embeds via Azure OpenAI, upserts to AI Search.

**Container build:** multi-stage Dockerfile (uv install → slim runtime, non-root user, both API + worker entrypoints). `COPY ui ./ui` serves the Claims Console at `/`.

**CI/CD:** `.github/workflows/cd.yml` — push to main → gate (ruff + mypy + pytest + eval) → `az acr build` → deploy both API + Worker Container Apps. Auth is **keyless OIDC** (GitHub → Azure federation, no stored secret). OIDC federated credentials for both `ref:refs/heads/main` and `environment:production`.

**IaC:** Bicep provisions ACR (Basic) + Container Apps environment (Log Analytics-backed) alongside the M10 data services.

**Tests** (`tests/test_m11_entrypoints.py`): worker starts/processes/cancels cleanly over fakes; ingestion populates the vector store with searchable chunks. (244 tests)

---

## M12 — AuthN/AuthZ + Claims Console UI ✅

**Role-based access control** with Container Apps EasyAuth + Entra ID — no token-validation code.

**Auth module** (`src/claimpilot/api/auth.py`):
- `CallerIdentity` model with `user` + `roles`
- `get_caller()` reads EasyAuth headers (`X-MS-CLIENT-PRINCIPAL-NAME` + `X-MS-CLIENT-PRINCIPAL`) in production; falls back to `X-Debug-Role` header **only when `allow_debug_role=True`** (default: `False`)
- When EasyAuth headers absent and debug off → anonymous caller with `read-only` role (no admin/adjuster privileges)
- `require_role("admin")` dependency → returns 403 with clear detail

**Protected routes:**
- `POST /v1/claims/{id}/decision` — admin only (403 for adjuster)
- `GET /v1/claims?status=escalated` — admin only
- `POST /v1/claims` / `GET /v1/claims/{id}` — open to all roles
- `GET /v1/me` — returns caller identity + roles

**Claims Console UI** (`ui/index.html`):
- React 18 + Tailwind single-file app served at `/` via FastAPI StaticFiles
- Role-aware shell: fetches `/v1/me` on mount, dev-mode role switcher (Adjuster/Admin)
- **Operator view:** Submit, Live, Decision, Evals — escalated claims show "Pending adjuster review"
- **Admin view:** all above + Admin tab with escalated claims queue table → click-through to reasoned packet + Approve/Deny
- Evals tab: case results as formatted table with pass/fail badges

**Tests:** 5 new auth tests — decision 403 for adjuster, 200 for admin; debug-role ignored when `allow_debug_role=False`; escalated list 403 for non-admin; `/v1/me` returns roles. (249 tests total)

**Gate (249 tests):** `ruff` clean · `mypy --strict` (70 source files) · 249/249 tests pass.

---

## What's done
**M0–M12 complete, gated, deployed, and live.** The full system — from claim submission through multi-agent adjudication to human review — runs end-to-end on Azure Container Apps with real GPT-5.2 decisions, keyless OIDC CI/CD, and role-based access control. Every push to main re-runs the eval gate and auto-deploys.
