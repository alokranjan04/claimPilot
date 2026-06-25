# BUILD_PLAN.md — ClaimPilot milestones

Work top to bottom. Each milestone is sized for one focused Claude Code session. Don't start a milestone until the previous one's acceptance criteria pass. The **Prompt** line is a ready-to-paste kickoff for Claude Code; refine as needed.

> Rule of thumb: implement against the spec section named, with fakes only, test-first. Cloud providers arrive at M7+.

---

## M0 — Project skeleton & tooling
**Spec:** master §14 (repo structure), CLAUDE.md (commands).
**Build:** `pyproject.toml` (uv, ruff, mypy strict, pytest), `Makefile` (`make check`), pre-commit, package skeleton with the directory map, a trivial `/healthz` FastAPI app, one passing smoke test, CI config placeholder.
**Acceptance:** `make check` passes; `uvicorn` serves `/healthz`; empty packages importable.
**Prompt:** *"Implement M0 from docs/BUILD_PLAN.md following CLAUDE.md. Set up tooling and the package skeleton, a /healthz endpoint, and a smoke test. Make `make check` green."*

## M1 — Domain models (typed boundaries)
**Spec:** master §8 (data contracts).
**Build:** Pydantic v2 models — `RawClaim`, `ClaimFacts`, `Citation`, `PolicyContext`, `CoverageOpinion`, `RiskAssessment`, `SettlementProposal`, `ComplianceVerdict`, `StepTrace`, `AgentError`, and `ClaimState` (the graph state). Validators (e.g., non-empty citations on a coverage decision; `Decimal` for money).
**Acceptance:** models + validator unit tests green; mypy strict clean.
**Prompt:** *"Implement M1: the Pydantic contracts from master-spec §8 in src/claimpilot/models/, with validators and unit tests."*

## M2 — Provider interfaces + fakes
**Spec:** master §4–7; CLAUDE.md guardrails.
**Build:** `infra/interfaces.py` — `LLMClient`, `Embedder`, `VectorStore`, `DocExtractor`, `Queue`, `Checkpointer`. `infra/providers/fakes/` implementing all of them deterministically (seeded, no network). `infra/settings.py` + DI factory selecting providers by `PROVIDER` env (default `fake`).
**Acceptance:** fakes pass an interface-conformance test suite; DI returns fakes by default.
**Prompt:** *"Implement M2: provider interfaces and deterministic in-memory fakes, plus settings/DI. Add conformance tests."*

## M3 — LangGraph skeleton (START→END with stub agents)
**Spec:** master §5 (orchestration), §4 (agents table).
**Build:** `graph/state.py`, `graph/build_graph.py` with all nodes (intake → policy_retrieval → coverage → fraud_risk → settlement → compliance → route → finalize/escalation) wired as stubs that mutate `ClaimState` and append `trace`. Conditional `route` edge using thresholds from settings. `error_handler` node.
**Acceptance:** integration test runs a fake claim END-to-END both auto-approve and escalate paths; trace populated at every node.
**Prompt:** *"Implement M3: the LangGraph state machine from master-spec §5 with stub agents, conditional routing, and an e2e integration test over fakes."*

## M4 — RAG pipeline (over fakes, then real retrieval)
**Spec:** master §7.
**Build:** `rag/` ingest + structure-aware chunking + embed (fake embedder) + hybrid retrieve (BM25 + dense) + rerank interface + grounding with citations + "insufficient context" path. Use a small bundled synthetic policy corpus fixture.
**Acceptance:** retrieval returns cited chunks; grounding test proves no-citation answers are rejected; "insufficient context → escalate" path covered.
**Prompt:** *"Implement M4: the RAG pipeline per master-spec §7 against the fake embedder/vector store, with a synthetic policy corpus fixture and grounding tests."*

## M5 — Real agents (intake, policy-RAG, coverage, fraud, settlement, compliance)
**Spec:** master §4; per-agent acceptance in `docs/specs/`.
**Build:** replace each stub with a real agent: prompt + structured-output call via `LLMClient` (fake returns scripted structured responses in tests), tool calls via MCP interface. Keep agents pure and unit-testable.
**Acceptance:** each agent has unit tests with the fake LLM; full graph produces correct dispositions on the golden fixtures.
**Prompt:** *"Implement M5: replace stub agents with real implementations per master-spec §4, one agent per commit, each with unit tests using the fake LLM."*

## M6 — MCP tool servers
**Spec:** master §6.
**Build:** `mcp_servers/` for `policy_db`, `claims_history`, `fraud_signals`, `regs` — typed tool schemas, validation, authz at boundary, graceful errors. Backed by fakes/fixtures locally. Agents call tools through the MCP interface.
**Acceptance:** MCP servers start; tool-call correctness tests pass; agents consume tools via the interface.
**Prompt:** *"Implement M6: the four MCP tool servers from master-spec §6 with typed schemas and tests; wire agents to call them through the interface."*

## M7 — Evaluation harness + CI gate
**Spec:** master §11.
**Build:** `evals/` golden dataset (50–100 synthetic claims), metrics (decision accuracy, citation faithfulness via LLM-as-judge/Ragas-style, tool-call correctness, escalation precision/recall, latency, cost), `run_evals.py`, and a CI job that fails on regression beyond tolerance.
**Acceptance:** `uv run python evals/run_evals.py` emits a scorecard; CI gate blocks on regression.
**Prompt:** *"Implement M7: the eval harness and golden dataset per master-spec §11, plus a CI gate that fails on metric regression."*

## M8 — API surface + async queue + checkpointing
**Spec:** master §9, §10.
**Build:** real FastAPI routes (`POST /v1/claims`, `GET /v1/claims/{id}`, SSE `/stream`, `POST /v1/claims/{id}/decision`, `GET /v1/evals/latest`). Submission enqueues via `Queue` (fake = in-memory); worker consumes and runs the graph; `Checkpointer` (fake = in-memory) enables pause/resume for human decisions.
**Acceptance:** submit→process→fetch works e2e offline; escalation can be resolved via the decision endpoint; SSE streams steps.
**Prompt:** *"Implement M8: the FastAPI surface, async queue worker, and checkpointing from master-spec §9–10, fully working over fakes with e2e tests."*

## M9 — Observability + cost meter
**Spec:** master §12.
**Build:** `observability/` — OpenTelemetry spans per node, structured JSON logs (no PII), a cost meter aggregating per-claim token cost/latency, exposed on the eval scorecard.
**Acceptance:** a run emits spans + a cost/latency summary; logs are structured and PII-free.
**Prompt:** *"Implement M9: observability and the cost meter per master-spec §12, with tests asserting trace completeness and no-PII logging."*

## M10 — First real provider: Azure
**Spec:** `docs/specs/10-deploy-azure.md`; master §6.
**Build:** `infra/providers/azure/` implementing the interfaces — Azure OpenAI (`LLMClient`, `Embedder`), Azure AI Search (`VectorStore`), Document Intelligence (`DocExtractor`), Service Bus (`Queue`), Cosmos DB (`Checkpointer`). Selected by `PROVIDER=azure`. Bicep/Terraform baseline in `infra/iac/`. No core code changes.
**Acceptance:** with Azure creds, `PROVIDER=azure` runs a real claim end-to-end; `PROVIDER=fake` still passes all tests unchanged.
**Prompt:** *"Implement M10: Azure provider implementations behind the existing interfaces per docs/specs/10-deploy-azure.md. Core/graph/agents code must not change. Add an IaC baseline."*

## M11 — Containerize + CI/CD + deploy
**Spec:** azure spec §4; master §10.
**Build:** Dockerfile(s), Azure Pipelines (lint → type → test → build → push ACR → eval gate → deploy Container Apps with revision canary), Key Vault + Managed Identity, Private Endpoints in IaC.
**Acceptance:** pipeline green incl. eval gate; deployed API serves a claim; rollback documented.
**Prompt:** *"Implement M11: containerization, Azure Pipelines with the eval gate, and Container Apps deploy per the azure spec, with IaC for identity/network."*

---

### Optional later
- **M12** — Add AWS and/or GCP providers behind the same interfaces (specs 11/12). Proves portability — a great interview point.
- **M13** — GraphRAG layer for multi-hop policy questions.
- **M14** — Multi-tenant isolation (per-tenant indexes, storage, identity).

### Demo milestone (cut line)
After **M7**, you already have a defensible, test-gated, offline-runnable showcase. M8–M11 make it production-grade on Azure.
