# ClaimPilot — Production-Ready Project Specification
### Autonomous Insurance Claims Adjudication with Multi-Agent Orchestration

**Author:** Alok Ranjan · **Status:** Engineering Spec v1.0 · **Stack:** Python · LangGraph · MCP · RAG · FastAPI

> A portfolio-grade, enterprise-shaped system: ingests a claim, adjudicates it through a graph of specialist agents over policy/regulatory knowledge, and either auto-settles within thresholds or escalates to a human with a fully cited, auditable trail. Built to demonstrate complexity handling, clean reviewable Python, MCP, LangGraph orchestration, a real RAG pipeline, an evaluation harness, FastAPI, and horizontal scalability.

---

## 1. Problem Statement & Why It Matters

Insurance claims adjudication is slow, inconsistent, and expensive: an adjuster manually reads the claim, cross-references the policy, checks coverage and exclusions, looks for fraud signals, computes a settlement, and documents a decision that must survive audit. ClaimPilot automates the deterministic 70–80% while keeping a human in the loop for the ambiguous, high-value, or high-risk tail — with every decision grounded in cited policy clauses so it's defensible.

**Business outcomes it targets:** lower cycle time per claim, consistent decisions, reduced leakage from misapplied coverage, and a complete audit trail. (These are the metrics you put on the eval dashboard.)

## 2. Goals & Non-Goals

**Goals**
- End-to-end adjudication from raw FNOL (First Notice of Loss) to a decision with citations.
- Justified multi-agent decomposition with explicit orchestration and human-in-the-loop.
- Production concerns made real: evaluation gates, observability, safe rollout, auditability.
- A codebase that is itself evidence of engineering quality (typed, tested, reviewable).

**Non-Goals (state these in interviews — scoping is a senior signal)**
- Not a real underwriting engine; uses synthetic/public policy corpora.
- No real PII or live insurer systems — integrations are simulated via MCP servers.
- Not building a model from scratch — orchestrating frontier LLM APIs.

## 3. System Architecture (high level)

```
                         ┌──────────────────────────────────────────────┐
   Client / Demo UI  ──▶ │  FastAPI Gateway  (async, streaming, authz)    │
                         └───────────────┬──────────────────────────────┘
                                         │ enqueue ClaimJob
                                ┌────────▼────────┐
                                │  Queue (Redis/   │   batch + backpressure
                                │  Kafka)          │
                                └────────┬────────┘
                                         │
                          ┌──────────────▼───────────────┐
                          │   LangGraph Orchestrator      │  ← state machine
                          │   (Supervisor + specialists)  │
                          └───┬───────┬───────┬───────┬───┘
            tools via MCP     │       │       │       │
         ┌────────────────────┼───────┼───────┼───────┼────────────┐
         ▼                    ▼       ▼       ▼       ▼            ▼
   ┌───────────┐      ┌────────────┐ ┌──────┐ ┌────────┐  ┌──────────────┐
   │ Policy DB │      │ Claims-Hist│ │Fraud │ │ RAG /  │  │ Settlement   │
   │ MCP server│      │ MCP server │ │Signal│ │ Vector │  │ rules engine │
   └───────────┘      └────────────┘ └──────┘ │ store  │  └──────────────┘
                                              └────────┘
        Cross-cutting:  Observability (Langfuse) · Eval harness (CI gate) · Audit log (Postgres)
```

## 4. Multi-Agent Design (orchestrator–worker)

A **Supervisor** owns routing and the overall state; specialists are narrow, independently testable, and each has its own tools and prompt. Every agent justifies its existence against a single-agent baseline (decision quality, latency, cost).

| Agent | Responsibility | Tools (via MCP / local) | Key output |
|---|---|---|---|
| **Supervisor** | Route by state, enforce thresholds, decide auto vs. escalate | — (control logic) | next node, final disposition |
| **Intake & Extraction** | Parse FNOL + attachments into structured `ClaimFacts` | doc parser, OCR (stub) | `ClaimFacts` |
| **Policy Retrieval (RAG)** | Find governing clauses, coverage, exclusions | `policy_db.search`, vector retriever | cited `PolicyContext` |
| **Coverage Decision** | Determine covered/denied/partial with rationale | reasoning + `PolicyContext` | `CoverageOpinion` + citations |
| **Fraud / Risk** | Score fraud signals, flag anomalies | `claims_history.lookup`, `fraud_signals.score` | `RiskAssessment` |
| **Settlement** | Compute payable amount per coverage & limits | `settlement_rules.compute` | `SettlementProposal` |
| **Compliance / Audit** | Verify regulatory + internal-policy adherence; assemble trail | `regs.search`, audit writer | `ComplianceVerdict`, audit record |

**Escalation rule (Supervisor):** auto-approve only if `coverage.confidence ≥ τ1` AND `risk.score ≤ τ2` AND `amount ≤ τ3` AND `compliance.passed`. Otherwise → human queue with the full reasoned packet.

## 5. LangGraph Orchestration

**State schema** (single typed object threaded through the graph):

```python
class ClaimState(TypedDict):
    claim_id: str
    raw_input: RawClaim
    facts: ClaimFacts | None
    policy_context: PolicyContext | None
    coverage: CoverageOpinion | None
    risk: RiskAssessment | None
    settlement: SettlementProposal | None
    compliance: ComplianceVerdict | None
    disposition: Literal["auto_approved","auto_denied","escalated"] | None
    trace: list[StepTrace]          # every node appends: inputs, outputs, citations, cost, latency
    errors: list[AgentError]
```

**Graph topology**
```
START → intake → policy_retrieval → coverage_decision → fraud_risk → settlement → compliance → route
route ──(pass + within thresholds)──▶ finalize_auto → END
route ──(low conf / high risk / high amount / compliance fail)──▶ human_escalation → END
any node on hard error ──▶ error_handler → human_escalation
```

**Design choices to defend in interview**
- **Explicit graph over free-form ReAct:** deterministic, debuggable, testable, replayable from any node.
- **Conditional edges** carry the business logic; the LLM proposes, the graph disposes.
- **Checkpointing** (LangGraph checkpointer → Redis/Postgres) so long-running claims survive restarts and support human-in-the-loop resume.
- **Every node appends to `trace`** — this is what makes the system auditable and powers the eval harness.

## 6. MCP Servers (reusable, standardized tool exposure)

Implement enterprise integrations as **MCP servers** rather than hardcoded functions, so tools are reusable across agents and demonstrably standards-based.

- **`policy-db` server** — `search(query, policy_id)`, `get_clause(clause_id)` over the policy corpus.
- **`claims-history` server** — `lookup(claimant_id)`, `prior_claims(policy_id)` (synthetic history DB).
- **`fraud-signals` server** — `score(claim_facts)` returning weighted signal features.
- **`regs` server** — `search(jurisdiction, topic)` over regulatory text.

Each server: typed tool schemas, authz at the boundary, input validation, idempotent reads, graceful errors. (Talking point: "the model never holds credentials; the MCP boundary does.")

## 7. RAG Pipeline

- **Corpus:** public/synthetic insurance policy documents + regulatory text; chunked along document structure (sections/clauses), not fixed windows.
- **Retrieval:** hybrid **BM25 + dense embeddings**, then a cross-encoder **re-ranker** for precision.
- **Grounding discipline:** answer only from retrieved context; **mandatory citations** (clause IDs); explicit "insufficient context → escalate" path.
- **Vector store:** `pgvector` (co-located with the audit/transactional DB) for the demo; pluggable to Pinecone/Weaviate for scale.
- **Freshness:** incremental re-indexing job on corpus change, not full rebuilds.
- **Faithfulness check** runs in the eval suite and on sampled production traffic.

## 8. Data Contracts (Pydantic — typed everywhere)

```python
class RawClaim(BaseModel):
    claim_id: str
    policy_number: str
    fnol_text: str
    attachments: list[Attachment] = []

class ClaimFacts(BaseModel):
    incident_type: str
    incident_date: date
    claimed_amount: Decimal
    location: str
    parties: list[Party]
    extracted_fields: dict[str, str]

class Citation(BaseModel):
    clause_id: str
    document: str
    snippet: str

class CoverageOpinion(BaseModel):
    decision: Literal["covered","denied","partial"]
    confidence: float = Field(ge=0, le=1)
    rationale: str
    citations: list[Citation]            # non-empty enforced by validator

class SettlementProposal(BaseModel):
    payable_amount: Decimal
    deductible_applied: Decimal
    limit_applied: Decimal
    breakdown: list[LineItem]
```

Strict typing on every agent/tool boundary is the backbone of "handling complexity" and makes the code review-friendly and unit-testable.

## 9. FastAPI Surface

```
POST   /v1/claims                 → submit a claim (returns claim_id, async)
GET    /v1/claims/{id}            → status + disposition + trace
GET    /v1/claims/{id}/stream     → SSE stream of agent steps (great for demo)
POST   /v1/claims/{id}/decision   → human approve/override on escalated claim
GET    /v1/evals/latest          → latest eval-run scorecard
GET    /healthz  /readyz         → liveness / readiness
```
- Async handlers; submission enqueues a `ClaimJob` and returns immediately.
- Dependency-injected LLM/vector/MCP clients (swap real ↔ fake for tests).
- Pydantic request/response models; OpenAPI auto-docs.

## 10. Scalability & Infra

- **Stateless API + worker pool**; claims processed off a queue (Redis Streams for the demo, Kafka-ready) for batch throughput and backpressure.
- **Agent state & checkpoints** in Redis/Postgres — workers are disposable.
- **Model routing:** cheap/fast model for extraction & retrieval steps; strong model for coverage decision — measured cost/claim, not guessed.
- **Caching:** semantic cache for repeated policy queries; prompt/KV caching where supported.
- **Containerized** (Docker) → Cloud Run / Kubernetes; autoscale on queue depth.
- **Cost & latency budgets** per node, enforced and dashboarded.

## 11. Evaluation Harness (your differentiator)

- **Golden dataset:** 50–100 synthetic claims with known correct dispositions, coverage outcomes, and expected citations.
- **Metrics:** decision accuracy, citation **faithfulness/groundedness** (Ragas + LLM-as-judge calibrated to labels), tool-call correctness, escalation precision/recall, p50/p95 latency, cost/claim.
- **CI gate:** GitHub Action runs the suite on every PR; a regression beyond tolerance **blocks merge**. (This single feature beats 90% of portfolio projects.)
- **Online evals:** sample production traffic, track drift, alert on faithfulness drop; rollback path documented.

## 12. Observability

- **Langfuse** (or OpenTelemetry) tracing on every agent step: prompt, retrieved context, tool calls, tokens, cost, latency.
- A small **dashboard** (or Langfuse views) showing cost/claim, latency distribution, escalation rate, faithfulness over time — screenshot this for the interview.

## 13. Security, Compliance & Responsible AI

- PII redaction before any third-party model call; secrets never in prompts.
- Authz enforced at the MCP boundary; least-privilege tool access.
- **Full audit log** (immutable Postgres table): every decision, its citations, the model/version, and the human override if any.
- Prompt-injection defenses on document inputs; output guardrails (schema + policy checks).
- Human-in-the-loop mandatory for high-value/high-risk dispositions.

## 14. Repository Structure

```
claimpilot/
├── README.md                      # architecture, demo, results — see §17
├── pyproject.toml                 # uv/poetry, ruff, mypy, pytest config
├── .pre-commit-config.yaml        # ruff + mypy + tests on commit
├── .github/workflows/ci.yml       # lint, type-check, unit tests, EVAL GATE
├── docker-compose.yml             # api + worker + redis + postgres(pgvector)
├── docs/
│   ├── architecture.md  +  architecture.png
│   └── decisions/                 # ADRs — shows engineering maturity
├── src/claimpilot/
│   ├── api/                       # FastAPI app, routes, deps, schemas
│   ├── graph/                     # LangGraph: state, nodes, edges, build_graph()
│   ├── agents/                    # one module per agent + prompts
│   ├── rag/                       # ingest, chunk, retrieve, rerank
│   ├── mcp_servers/               # policy_db, claims_history, fraud_signals, regs
│   ├── models/                    # Pydantic contracts
│   ├── infra/                     # llm client, vector client, queue, cache, settings
│   └── observability/             # tracing, cost meter
├── evals/
│   ├── golden/                    # dataset
│   ├── metrics.py                 # ragas + judges + assertions
│   └── run_evals.py
└── tests/                         # unit (fakes) + integration (graph e2e)
```

## 15. Tech Stack

Python 3.12 · FastAPI · LangGraph + LangChain · OpenAI API (GPT-4o) with model routing · `mcp` (Model Context Protocol SDK) · Postgres + pgvector · Redis · Ragas + LLM-as-judge · Langfuse · Docker · GitHub Actions · uv + ruff + mypy + pytest.

## 16. Build Plan (≈3–4 focused weeks)

1. **Week 1 — Skeleton & graph:** FastAPI + Pydantic contracts; LangGraph state graph with stubbed agents executing end-to-end; first MCP server (`policy-db`); docker-compose up. *Milestone: a fake claim flows START→END.*
2. **Week 2 — RAG & core decision:** ingest corpus, hybrid retrieval + rerank, Intake + Policy-Retrieval + Coverage agents producing cited opinions. *Milestone: real coverage decisions with citations.*
3. **Week 3 — Full panel & scale:** Fraud, Settlement, Compliance agents; conditional escalation; Redis queue + checkpointing; human-decision endpoint. *Milestone: auto vs. escalate works under load.*
4. **Week 4 — Eval, observability, polish:** golden dataset + metrics + CI gate; Langfuse dashboard; README, architecture diagram, demo script, ADRs. *Milestone: green eval gate + recorded demo.*

**MVP cut line (if time-boxed):** Weeks 1–2 + the eval gate is already a credible, defensible showcase. Weeks 3–4 make it enterprise-grade.

## 17. Interview Assets & Demo Script

**Have ready:** public GitHub repo, the `architecture.png`, the Langfuse/eval dashboard screenshot, and a 3-minute live demo.

**Demo flow (3 min):** submit a clean claim → watch the SSE stream show each agent step with citations → it auto-approves. Then submit an ambiguous/high-value claim → it escalates with a full reasoned packet → you approve via the human endpoint. Close on the eval dashboard: "every change is gated on these numbers."

**Narrative line:** *"At Sutherland I led an agent-assist platform that helped 150+ human agents. ClaimPilot is the next step on that curve — from assisting a human to autonomously adjudicating with a human safety net — built with the production discipline (evals, observability, audit) that lets you actually ship GenAI in a regulated domain."*

**Anticipated probes (rehearse):** why multi-agent vs single? · how do you stop hallucinated citations? · how do you evaluate non-deterministic output? · how does this scale to 10k claims/day? · what's the human-in-the-loop boundary and why? — all answered by sections above; cross-reference your GenAI Architect Round-2 prep.

## 18. Stretch Ideas (mention as "roadmap," don't build now)
- A/B model routing experiment with cost/quality trade-off report.
- Self-improving retrieval: mine escalations to expand the golden set.
- A second domain (healthcare claims) reusing the same graph to prove platform generality.
