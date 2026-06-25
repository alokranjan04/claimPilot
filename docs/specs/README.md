# Specs — source of truth

These specs define ClaimPilot. Code is written *against* them. If code and spec disagree, the spec wins — or the spec is updated first (with an ADR), then the code.

## Index

| File | What it covers | Drives milestones |
|---|---|---|
| `00-master-spec.md` | Full system: problem, architecture, agents, LangGraph topology, MCP, RAG, Pydantic contracts, FastAPI, scalability, eval, observability, security, repo, build plan | M0–M9 |
| `10-deploy-azure.md` | **Target cloud.** Azure-native mapping: Azure OpenAI, AI Search, Document Intelligence, Container Apps, Service Bus, Cosmos DB, AI Foundry Eval, Content Safety, Entra/Key Vault, Bicep/Terraform | M10–M11 |
| `11-deploy-aws.md` | AWS-native equivalent (Bedrock, etc.) — optional portability milestone | M12 (optional) |
| `12-deploy-gcp.md` | GCP-native equivalent (Vertex AI, etc.) — optional portability milestone | M12 (optional) |
| `20-agent-coverage.md` | Coverage-decision agent: grounded prompt, structured output, citation enforcement, edge cases, acceptance tests. Reference pattern for all agents. | M5 |
| `21-rag-pipeline.md` | RAG pipeline: chunking, hybrid retrieval, rerank, grounding contract, config, edge cases, acceptance tests. | M4 |
| `22-eval-metrics.md` | Eval harness: golden set, exact metric definitions, thresholds, CI gate, edge cases, acceptance tests. | M7 |

## How specs map to code
- Master §4 (agents) → `src/claimpilot/agents/` + `graph/`
- Master §5 (orchestration) → `src/claimpilot/graph/`
- Master §6 (MCP) → `src/claimpilot/mcp_servers/`
- Master §7 (RAG) → `src/claimpilot/rag/`
- Master §8 (contracts) → `src/claimpilot/models/`
- Master §9 (API) → `src/claimpilot/api/`
- Master §11 (eval) → `evals/`
- Master §12 (observability) → `src/claimpilot/observability/`
- Azure spec §1, §3 → `src/claimpilot/infra/providers/azure/`
- Azure spec §4 → `infra/iac/` + `azure-pipelines.yml`

## Component spec stubs (optional, for deeper milestones)
When a milestone needs more detail than the master spec gives, add a focused component spec here and reference it from `BUILD_PLAN.md`, e.g.:
- `20-agent-coverage.md` — coverage-decision agent: inputs, prompt strategy, output schema, edge cases, acceptance tests.
- `21-rag-pipeline.md` — chunking rules, hybrid weights, rerank, grounding contract.
- `22-eval-metrics.md` — exact metric definitions, thresholds, golden-set schema.

Keep each component spec to: **Purpose → Inputs/Outputs (typed) → Behavior → Edge cases → Acceptance tests.** That shape is what makes Claude Code implement it correctly the first time.

## Target cloud: Azure
This build deploys to **Azure** (see `10-deploy-azure.md`). The core stays provider-agnostic so AWS/GCP remain pluggable, but Azure is the one we wire, containerize, and ship.
