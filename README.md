# ClaimPilot

Autonomous insurance claims adjudication. A claim enters; a graph of specialist agents adjudicates it over policy/regulatory knowledge using RAG; it either auto-settles within thresholds or escalates to a human with a fully cited, auditable trail.

Built with Python, LangGraph, MCP, RAG, and FastAPI. **Provider-agnostic core, fakes-first**, deployable on **Azure** (Azure OpenAI, AI Search, Document Intelligence, Container Apps).

## Why this exists
A portfolio-grade, enterprise-shaped system demonstrating: multi-agent orchestration, clean typed Python, MCP tool servers, a real RAG pipeline, an evaluation harness with a CI gate, observability, and horizontal scalability — with security and auditability as first-class concerns.

## Status
Built spec-driven, milestone by milestone — see `docs/BUILD_PLAN.md`.

## How it's built
- **Specs are the source of truth** — `docs/specs/` (start with `00-master-spec.md`; Azure target in `10-deploy-azure.md`).
- **CLAUDE.md** is the build contract (conventions, guardrails, definition of done).
- **`docs/SPEC_DRIVEN_WORKFLOW.md`** explains the Claude Code workflow.

## Quickstart (offline, fakes)
```bash
uv sync --extra dev
make check                                   # ruff + mypy + pytest
uv run uvicorn claimpilot.api.main:app --reload
# submit a sample claim:
curl -X POST localhost:8000/v1/claims -H 'content-type: application/json' \
     -d @tests/fixtures/sample_claim.json
```

## Run on Azure (M10+)
```bash
uv sync --extra dev --extra azure
export PROVIDER=azure
# ...Azure resource config via env / Key Vault; see docs/specs/10-deploy-azure.md
```

## Repo map
See CLAUDE.md → "Repo map". Core code depends only on interfaces in `src/claimpilot/infra/`; Azure/AWS/GCP plug in behind them.

## License
Personal portfolio project. Synthetic/public data only — no real PII.
