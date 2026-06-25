# ClaimPilot on Azure — Azure OpenAI Native Deployment Spec
### Companion to ClaimPilot_Project_Spec.md · All-Azure stack

**Status:** Deployment Spec v1.0 · **Principle:** every component is a first-party Azure service. LangGraph remains the orchestration framework (open-source); it runs on **Azure Container Apps** (or as **Azure AI Foundry Agent Service** if you prefer a managed agent runtime). The FastAPI surface, Pydantic contracts, LangGraph topology, and agent design from the main spec are unchanged — only implementations swap.

---

## 1. Component → Azure Service Mapping

Primary is what I'd build first; **Alternative(s)** is the in-Azure option I'd swap to under different scale/cost/control needs; **Why & key benefits** is the one-line defense for the interview.

| ClaimPilot component | **Primary (Azure) choice** | **Alternative(s) within Azure** | **Why this choice & key benefits** |
|---|---|---|---|
| LLM reasoning | **Azure OpenAI — GPT-4o** (decisions) + **GPT-4o mini** (extraction/routing) | **Azure AI Foundry Model Catalog** (Llama, Mistral, Phi, Cohere); self-host on **Azure ML** | Frontier OpenAI models inside your tenant/region with Entra + Private Link + content filtering. Two-tier routing = strong judgment on decisions, cheap on volume. Catalog/AML for model choice & self-hosting. |
| Embeddings | **Azure OpenAI `text-embedding-3-large`** | `text-embedding-3-small` (cost); models via AI Foundry | Managed, same security envelope as the LLM; small variant to cut cost/latency; catalog models if you need open embeddings. |
| Vector store / retrieval | **Azure AI Search** (vector + hybrid + **semantic ranker**) | **Cosmos DB for PostgreSQL `pgvector`** (demo); **Cosmos DB for MongoDB vCore** vector; **Azure Cache for Redis** vector | AI Search = hybrid retrieval *and* an integrated L2 reranker in one managed service — less to build. pgvector keeps vectors with transactional data (cheaper demo); Cosmos/Redis for other data-model fits. |
| Re-ranking | **Azure AI Search semantic ranker** (built-in L2) | **Cohere Rerank** via AI Foundry; self-hosted cross-encoder | Reranking included in AI Search → no extra component. Cohere/self-host only for a domain-tuned reranker. |
| Managed RAG | **Azure AI Search** + **Azure AI Foundry "On Your Data"** | fully hand-built pipeline | AI Search is the managed retrieval layer; "On Your Data" wires grounding to the model with citations fast. Hand-built shows depth + full grounding control. |
| Document intake / OCR | **Azure AI Document Intelligence** (prebuilt + custom models) | **GPT-4o vision**; **Azure AI Vision** OCR | Purpose-built for forms → structured fields + confidence + table extraction, custom-trainable. GPT-4o vision for unstructured docs; AI Vision for plain OCR. |
| Agent runtime | **LangGraph on Azure Container Apps** | **Azure AI Foundry Agent Service** (managed); **AKS**; **Azure Functions** | Container Apps = serverless containers w/ scale-to-zero, KEDA autoscaling, full graph control. Foundry Agent Service for a managed agent loop; AKS for heavy/stateful; Functions for light steps. |
| API gateway | **FastAPI on Azure Container Apps** + **Azure API Management** + **App Gateway** | **Azure App Service**; **AKS** ingress | Container Apps scales to zero and deploys fast; APIM adds auth, quotas, dev portal. App Service for a classic PaaS host. |
| Async queue | **Azure Service Bus** | **Azure Storage Queues** (simple/cheap); **Event Grid** (events); **Event Hubs** (Kafka/streaming) | Service Bus = durable, ordered, dead-letter, sessions, backlog autoscale. Storage Queues cheapest; Event Grid to wire Blob/Doc-Intelligence events; Event Hubs for high-throughput streaming. |
| Agent state / checkpoints | **Azure Cosmos DB** (LangGraph checkpointer) | **Azure SQL / PostgreSQL Flexible Server**; **Table Storage** | Cosmos DB = serverless, low-latency, global, ideal for pause/resume human-in-the-loop. SQL/Postgres if state is relational; Table Storage cheapest for simple state. |
| Cache | **Azure Cache for Redis** | in-process LRU | Sub-ms semantic/response cache cuts model cost & latency; in-process when a managed cache isn't justified. |
| Audit log | **Azure SQL / PostgreSQL Flexible Server** + **Azure Data Explorer / Synapse** (analytics) | **Cosmos DB** append; **Log Analytics** | SQL = transactional, queryable, immutable audit; ADX/Synapse for analytics & Power BI. Cosmos for high write; Log Analytics if you want it alongside telemetry. |
| Object storage | **Azure Blob Storage** | **Azure Data Lake Storage Gen2** (analytics) | Durable, cheap, lifecycle tiers, CMK, event triggers to Document Intelligence. ADLS Gen2 if you need hierarchical/analytics layout. |
| Evaluation | **Azure AI Foundry Evaluation** (groundedness, relevance, coherence, custom) | **Ragas / DeepEval** on Container Apps; **Prompt Flow** batch eval | Native generation + RAG metrics incl. **groundedness**, integrated with tracing; logs to the Foundry project. OSS libs for portable evals; Prompt Flow for visual eval pipelines. |
| Guardrails / safety | **Azure AI Content Safety** (Prompt Shields, **Groundedness detection**, protected material) | model-level system prompts; self-hosted filters | Managed prompt-injection defense + a grounding/hallucination check purpose-built for RAG claims — a strong, defensible safety story. |
| Observability / tracing | **Azure Monitor** + **Application Insights** (distributed tracing) + **Log Analytics**; AI Foundry tracing | **OpenTelemetry → App Insights**; **Langfuse** on AKS | Unified, alerting built in, end-to-end traces across API→worker→AOAI→tools. OTel keeps you vendor-neutral; Langfuse for LLM-specific trace UX. |
| Metrics dashboard | **Power BI** over ADX/Synapse | **Azure Managed Grafana**; **Azure Workbooks** | Power BI = polished business scorecard (cost/claim, faithfulness over time). Grafana/Workbooks for ops-facing views. |
| CI/CD | **Azure DevOps Pipelines** + **Azure Container Registry** | **GitHub Actions** + OIDC; **Azure Deployment** stacks | Native pipeline runs the eval gate and deploys to Container Apps. GitHub Actions via OIDC (Workload Identity Federation) if the team lives on GitHub. |
| Secrets | **Azure Key Vault** | **App Configuration** (config); Managed HSM (keys) | Versioned secrets + rotation + RBAC + audit; App Config for non-secret config; Managed HSM for FIPS key custody. |
| AuthN/Z | **Microsoft Entra ID** + **Managed Identities** + **Entra External ID** (end-user) | **APIM** policies; app-level RBAC | Entra + Managed Identities = no secrets for service-to-service. External ID for customer sign-in; APIM policies to gate the API. |
| Compute (default) | **Azure Container Apps** | **AKS**; **App Service**; **Azure Functions** | Container Apps = serverless containers, scale-to-zero, KEDA. AKS for k8s/mesh; App Service classic PaaS; Functions for event handlers. |
| Network security | **VNet + Private Endpoints** (Private Link to AOAI/AI Search/Storage) + NSGs | **Azure Firewall**; **Service Endpoints** | Private Endpoints keep AOAI/Search/Storage traffic off the public internet — the headline regulated-domain control. Firewall for deep egress control. |
| PII protection | **Azure AI Language — PII detection** + **AI Content Safety** | **Microsoft Purview** (governance/discovery); regex/Presidio on Container Apps | Language PII + Content Safety redact before/within model calls; Purview for tenant-wide sensitive-data governance & lineage. |

## 2. Azure-Native Architecture

```
   End user / Demo UI
        │ HTTPS
        ▼
  Front Door ─▶ Azure API Management ─▶ ┌──────────────────────────────────┐
                                         │ Container Apps: FastAPI service   │ (scale-to-zero)
                                         └──────────────┬────────────────────┘
                                 publish ClaimJob       │
                                                        ▼
                                                 ┌──────────────┐   DLQ
                                                 │ Service Bus  │──────▶ (dead-letter)
                                                 └──────┬───────┘
                                                        ▼
                                          ┌──────────────────────────┐
                                          │ Container Apps: Worker     │
                                          │  runs LangGraph graph      │
                                          └──────────┬─────────────────┘
                                                     ▼
                  ┌──────────────────────────────────────────────────────┐
                  │  Supervisor + specialist agents (LangGraph)            │
                  └─┬─────────┬──────────┬──────────┬──────────┬──────────┘
   Azure OpenAI     │         │          │          │          │
   (GPT-4o / mini) ─┘  ┌──────▼─────┐ ┌──▼───────┐ ┌▼────────┐ ┌▼──────────┐
                       │ Document   │ │ AOAI     │ │ Azure AI │ │ MCP servers│
                       │Intelligence│ │ Embed    │ │ Search   │ │(Container │
                       │ (intake)   │ │          │ │(+ranker) │ │  Apps)    │
                       └────────────┘ └──────────┘ └──────────┘ └───────────┘
   + AI Content Safety (Prompt Shields + groundedness) on model calls
   State/Cache: Cosmos DB (checkpoints) · Azure Cache for Redis (cache)
   Data: Azure SQL (audit) · Blob (docs) · ADX/Power BI (metrics)
   Cross-cutting: Azure Monitor + App Insights · AI Foundry Eval · Key Vault · Entra ID · Private Endpoints
```

## 3. Layer-by-Layer Detail

### 3.1 Models — Azure OpenAI (model routing)
- **GPT-4o** for coverage decisions & compliance reasoning; **GPT-4o mini** for extraction, routing, query rewriting (cheap, fast, high volume).
- Deploy models in your **Azure OpenAI** resource; call with **Entra ID (managed identity)** auth, behind **Private Endpoints**, with built-in **content filtering**. Data stays in your tenant/region.
- **Structured outputs / JSON schema** + tool calling → maps to your Pydantic contracts.
- Add **AI Content Safety** (Prompt Shields + groundedness detection) around calls.

### 3.2 Intake — Azure AI Document Intelligence
FNOL forms/attachments land in **Blob Storage** → **Document Intelligence** (prebuilt or a custom-trained model) extracts structured fields + tables with confidence before the Intake agent runs. An **Event Grid** event can trigger processing. Demo win: upload a PDF claim → structured `ClaimFacts`.

### 3.3 RAG — two valid Azure paths
- **Path A (build, more to show):** chunk corpus → embed with `text-embedding-3-large` → index in **Azure AI Search** (vector + hybrid) → **semantic ranker** → ground with citations.
- **Path B (managed):** **Azure AI Foundry "On Your Data"** wires AI Search to the model with grounding + citations out of the box.
- **Recommendation:** build Path A (AI Search already includes the reranker, so it's both managed and deep). For the cheapest demo, Cosmos DB `pgvector` works.

### 3.4 Orchestration — LangGraph on Container Apps
- Keep the LangGraph state graph from the main spec; run it in a **Container Apps** worker triggered off Service Bus (KEDA scaler on queue depth).
- **Checkpointer → Cosmos DB** so human-in-the-loop claims pause/resume.
- Managed alternative: **Azure AI Foundry Agent Service** — mention as the "managed agent runtime" option.

### 3.5 Tools — MCP servers on Container Apps
Each MCP server (`policy-db`, `claims-history`, `fraud-signals`, `regs`) is a small **Container Apps** service over authenticated HTTP; **Managed Identity** for service-to-service auth; **Key Vault** for credentials; backing data in **Azure SQL / Cosmos DB**.

### 3.6 Async & state
- **Service Bus** `claims-submitted` (+ DLQ) drives Container Apps workers; **KEDA** autoscale on queue length. **Event Grid** to wire Blob/Doc-Intelligence events.
- **Azure Cache for Redis** for semantic/response cache.

### 3.7 Evaluation — Azure AI Foundry Evaluation
- Replace Ragas with **Foundry Evaluation**: built-in groundedness, relevance, coherence, fluency + **custom evaluators** (decision accuracy, citation correctness), integrated with tracing.
- Golden dataset in Blob/Foundry; results logged to the Foundry project / Azure Monitor; **CI gate** runs the eval from **Azure DevOps** and fails on regression.

### 3.8 Observability
- **Application Insights** distributed tracing across API→worker→AOAI→tools; **Azure Monitor** metrics + alerts (escalation rate, p95 latency, cost, errors); **Log Analytics** for structured per-node trace logs; AI Foundry tracing for agent steps.
- **Power BI** over ADX for the business scorecard screenshot.

### 3.9 Security & governance
- **Entra ID** + **Managed Identities** (no secrets); **Entra External ID** for end-user auth.
- **Private Endpoints / Private Link** for AOAI, AI Search, Storage, Cosmos; VNet-integrated Container Apps; NSGs.
- **Key Vault** (+ rotation); **CMK** on Storage/SQL/Cosmos.
- **AI Content Safety** + **AI Language PII** redaction; **Purview** for sensitive-data governance.
- Immutable audit in Azure SQL; **Azure Activity Log + Diagnostic Settings** for control-plane/data-access audit.

## 4. CI/CD & IaC (all Azure)
- **Source** → Azure Repos or GitHub; **Azure Pipelines** stages: lint (ruff) → type-check (mypy) → unit tests → build container → push to **ACR** → **run Foundry eval (gate)** → deploy to Container Apps (revision traffic-split canary).
- **IaC:** **Bicep** (native) or **Terraform** provisions AOAI, AI Search, Container Apps, Service Bus, Cosmos DB, Azure SQL, Key Vault, Entra, Storage. Keep in `infra/`.
- **Safe rollout:** Container Apps **revisions** with traffic splitting (10% → 100%) and instant rollback — your safe-rollout story, natively.

```
infra/
├── bicep/                     # or terraform/  (AOAI, AI Search, Container Apps, Service Bus, Cosmos, SQL, Key Vault...)
├── azure-pipelines.yml        # CI incl. eval gate
└── Dockerfile(s)
```

## 5. Cost & Footprint Notes (for the demo)
- Use **GPT-4o mini** for all but the final decision; route to **GPT-4o** only on decision/compliance nodes.
- For the demo, **AI Search Basic tier** or Cosmos `pgvector` keeps the index cheap.
- **Container Apps scale-to-zero** + Service Bus means near-zero idle cost between demos.
- Document Intelligence and Foundry Evaluation are pay-per-use — fine for a portfolio footprint.
- Set a **Cost Management budget + alert**; mention it — cost-awareness is a senior signal.

## 6. What Changes in the Codebase vs. the Generic Spec
- `infra/llm/` → Azure OpenAI client (Entra auth), model-router GPT-4o vs mini, Content Safety attached.
- `rag/` → AOAI embeddings + Azure AI Search (vector + semantic ranker).
- `agents/intake` → Document Intelligence client.
- `graph/` checkpointer → Cosmos DB.
- `infra/queue/` → Service Bus publisher/consumer (+ DLQ).
- `evals/` → Azure AI Foundry Evaluation jobs.
- `observability/` → OpenTelemetry → Application Insights + Log Analytics.
- CI → `azure-pipelines.yml`; add `infra/bicep` (or terraform).
- Unchanged: FastAPI surface, Pydantic contracts, LangGraph topology, agent design.

## 7. Interview Talking Points (Azure-native)
- *"Why Azure OpenAI over the public API?"* → models in your tenant/region, Entra + Private Link, built-in content filtering & Content Safety — the controls a regulated claims workload needs.
- *"How do you orchestrate?"* → LangGraph state machine on Container Apps (or Foundry Agent Service) — my graph logic intact, serverless + KEDA.
- *"Cheap and fast?"* → GPT-4o mini for volume, GPT-4o for decisions; Redis semantic cache; Container Apps scale-to-zero on Service Bus depth.
- *"Evaluate & gate releases?"* → AI Foundry Evaluation (groundedness + custom metrics) as an Azure Pipelines gate; results in the Foundry project.
- *"Secure?"* → Entra managed identities, Private Endpoints, Content Safety + PII redaction, CMK, diagnostic-log audit.
- *"Scale to 10k claims/day?"* → Service Bus + KEDA-autoscaled Container Apps, Cosmos checkpoints, AI Search index.

## 8. Build Order Delta (Azure-specific)
1. **Subscription setup:** create AOAI resource + model deployments, VNet + Private Endpoints, Entra app/managed identities, Bicep/Terraform baseline.
2. **AOAI wiring:** client + model router; embeddings + AI Search index; smoke-test a grounded RAG answer + Content Safety.
3. **Document Intelligence → Service Bus → Container Apps worker → LangGraph** end-to-end on a fake claim; Cosmos checkpoints.
4. **Foundry Evaluation + Pipelines gate**, then Azure Monitor alerts + Power BI dashboard.

> Note: Azure renames AI products often (Form Recognizer → Document Intelligence; Azure AI Studio → AI Foundry). Confirm current names, model availability, and regional quotas in the portal when you start — the architecture and service roles are what matter.
