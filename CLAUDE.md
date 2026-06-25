# CLAUDE.md — ClaimPilot

> Read this first. It is the contract for how we build ClaimPilot. Follow it exactly unless the human overrides.

## What we're building
ClaimPilot: an autonomous insurance claims adjudication system. A claim enters; a graph of specialist agents adjudicates it over policy/regulatory knowledge; it either auto-settles within thresholds or escalates to a human with a fully cited, auditable trail. Full intent lives in `docs/specs/00-master-spec.md`.

## How we work — spec-driven, test-first
1. **Spec is the source of truth.** Before writing code for a component, read its spec in `docs/specs/`. If the spec is ambiguous or wrong, STOP and ask — do not invent behavior.
2. **One milestone at a time.** Work the milestones in `docs/BUILD_PLAN.md` in order. Do not jump ahead. Each milestone has acceptance criteria; you are done only when they pass.
3. **Test-first.** For each unit of behavior: write the failing test, implement, make it pass, refactor. No feature is "done" without tests.
4. **Small, reviewable changes.** Prefer many small commits over one large one. Conventional Commits (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`).
5. **Record decisions.** Any non-obvious design choice → a short ADR in `docs/decisions/NNN-title.md`.

## Definition of Done (every milestone)
- [ ] Acceptance criteria in BUILD_PLAN met.
- [ ] `ruff` clean, `mypy` clean (strict), tests green.
- [ ] New behavior covered by tests (unit; integration where a graph path changed).
- [ ] Public functions typed and docstring'd; no `Any` without a comment justifying it.
- [ ] No secrets, keys, or real PII in code, fixtures, or logs.
- [ ] CHANGELOG / commit message explains the *why*.

## Architecture guardrails (do not violate)
- **Typed boundaries everywhere.** Every agent I/O and tool contract is a Pydantic model in `src/claimpilot/models/`. No untyped dicts crossing module lines.
- **Orchestration is an explicit LangGraph state machine** (`src/claimpilot/graph/`), not free-form agent loops. Business routing lives in conditional edges, not inside prompts.
- **Provider-agnostic core.** Core code depends on interfaces (`LLMClient`, `Embedder`, `VectorStore`, `DocExtractor`, `Queue`, `Checkpointer`) defined in `src/claimpilot/infra/interfaces.py`. Concrete providers (fakes, Azure, AWS, GCP) live behind them and are wired by config/DI — never imported directly in agents or graph.
- **Fakes-first.** A full local run uses in-memory fakes (no cloud, no API keys). `START→END` must always work offline for tests and demos.
- **Grounding discipline.** RAG answers cite sources and may return "insufficient context → escalate." Never fabricate citations.
- **Human-in-the-loop is a real graph node**, not an afterthought. Escalation must carry the full reasoned packet.
- **Every node appends to `trace`** (inputs, outputs, citations, cost, latency). This powers audit + eval. Don't skip it.

## Tech stack (pin in pyproject)
Python 3.12 · FastAPI · LangGraph + LangChain · Pydantic v2 · `uv` · `ruff` · `mypy` · `pytest` + `pytest-asyncio` · `httpx`. Cloud SDKs are added only in their provider module, only at the milestone that needs them.

## Commands (keep these working)
```bash
uv sync                       # install
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest -q              # all tests, offline, with fakes
uv run uvicorn claimpilot.api.main:app --reload   # run API locally
make check                    # ruff + mypy + pytest (the gate)
```

## Repo map
```
src/claimpilot/
  api/            FastAPI app, routes, deps, request/response schemas
  graph/          LangGraph: state, nodes, edges, build_graph()
  agents/         one module per agent (+ prompts); pure, testable
  rag/            ingest, chunk, embed, retrieve, rerank
  mcp_servers/    policy_db, claims_history, fraud_signals, regs
  models/         Pydantic contracts (the typed boundaries)
  infra/          interfaces.py + providers/{fakes,azure,aws,gcp}, settings, DI
  observability/  tracing, cost meter
evals/            golden dataset, metrics, run_evals.py
tests/            unit (fakes) + integration (graph e2e)
docs/specs/       the specs — source of truth
docs/decisions/   ADRs
```

## Conventions
- Config via `pydantic-settings`; a `PROVIDER=fake|azure|aws|gcp` env var selects providers. Default `fake`.
- Async throughout the API and graph; no blocking I/O in async paths.
- Errors are typed (`AgentError`) and handled in the graph's `error_handler` node — agents don't crash the run.
- Logging is structured JSON; never log prompts/PII at INFO. Money values use `Decimal`, never float.

## When in doubt
Ask. A wrong assumption encoded in code is more expensive than a clarifying question. Cite the spec section you're working from in your reasoning.
