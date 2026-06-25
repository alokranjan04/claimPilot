# ClaimPilot on Google Cloud — Vertex AI Native Deployment Spec
### Companion to ClaimPilot_Project_Spec.md · All-Google stack

**Status:** Deployment Spec v1.0 · **Principle:** every component is a first-party Google Cloud service. LangGraph remains the orchestration framework (open-source) but runs *on* Vertex AI Agent Engine, so the architecture is fully GCP-managed.

---

## 1. Component → Google Cloud Service Mapping

Primary choice is what I'd build first; the **Alternative(s)** column is the in-GCP option I'd swap to under different scale/cost/control needs; **Why & key benefits** is the one-line defense for the interview.

| ClaimPilot component | **Primary (Google) choice** | **Alternative(s) within GCP** | **Why this choice & key benefits** |
|---|---|---|---|
| LLM reasoning | **Vertex AI — Gemini 2.5 Pro** (decisions) + **Gemini 2.5 Flash** (extraction/routing) | Vertex **Model Garden** open models (Llama, Gemma) self-hosted; **Claude / Mistral on Vertex** | Frontier quality with in-tenant data, IAM, VPC-SC, regional residency. Two-tier routing = strong judgment where it matters, low cost on volume. Alternatives give model choice / no per-token lock-in when you need it. |
| Embeddings | **Vertex AI `text-embedding-005`** | `text-multilingual-embedding-002`; open embeddings (Gemma) on Model Garden | Managed, autoscaled, same security envelope as the LLM; multilingual variant for non-English policies; open model if embeddings must stay fully self-hosted. |
| Vector store / retrieval | **Vertex AI Vector Search** (scale) | **AlloyDB / Cloud SQL `pgvector`** (demo); **BigQuery vector search** (analytical) | Vector Search = low-latency ANN at billions of vectors. pgvector keeps vectors next to transactional data (cheaper, simpler for demo). BigQuery option when retrieval is batch/analytical. |
| Re-ranking | **Vertex AI Ranking API** (Discovery Engine) | self-hosted cross-encoder on Cloud Run / GKE | Managed precision lift with no model to host; self-host only if you need a custom domain-tuned reranker. |
| Managed RAG (optional) | **Vertex AI RAG Engine** | **Vertex AI Search** (Agent Builder); fully hand-built pipeline | RAG Engine removes chunk/embed/retrieve ops glue → faster to production. Vertex AI Search adds enterprise search UX. Hand-built shows depth and gives full control of grounding. |
| Document intake / OCR | **Document AI** (Custom Extractor / Form Parser) | **Gemini multimodal** direct PDF parsing; **Vision API** OCR | Purpose-built for forms → high-accuracy structured fields, confidence scores, human-review tooling. Gemini multimodal is simpler for unstructured docs; Vision API for plain OCR. |
| Agent runtime | **Vertex AI Agent Engine** (hosts LangGraph natively) | LangGraph in **Cloud Run** worker; **GKE** for full control; **Agent Builder / ADK** | Managed scaling, sessions, and tracing for agents with your graph intact. Cloud Run = full control + scale-to-zero; GKE for heavy/stateful; ADK if you adopt Google's native agent framework. |
| API gateway | **FastAPI on Cloud Run** + **API Gateway** + **Cloud Load Balancing** | **Apigee** (full API management); **GKE Ingress** | Cloud Run scales to zero and deploys in seconds; API Gateway adds auth/quotas. Apigee when you need monetization, dev portal, advanced API governance. |
| Async queue | **Pub/Sub** | **Cloud Tasks** (per-task rate control); **Eventarc** (event routing) | Pub/Sub = massive throughput, fan-out, dead-letter, backlog-based autoscaling. Cloud Tasks for fine-grained per-claim dispatch/retry; Eventarc to wire GCS/Document AI events. |
| Agent state / checkpoints | **Firestore** (checkpointer) | **Cloud SQL / AlloyDB**; **Spanner** (global) | Firestore = serverless, real-time, ideal for pause/resume human-in-the-loop. Cloud SQL if state is already relational; Spanner for global, strongly-consistent scale. |
| Cache | **Memorystore for Redis** | in-process LRU; **Firestore** TTL cache | Sub-ms semantic/response cache cuts model cost and latency; lighter options when a managed cache isn't justified. |
| Audit log | **Cloud SQL (Postgres)** + **BigQuery** (analytics) | **BigQuery-only** append; **Bigtable** (high write) | Cloud SQL = transactional, queryable, immutable audit; BigQuery for analytics/Looker. BigQuery-only is cheaper at scale; Bigtable for very high write volume. |
| Object storage | **Cloud Storage (GCS)** | — (canonical) | Durable, cheap, lifecycle rules, CMEK, event triggers to Document AI; the standard for documents & artifacts. |
| Evaluation | **Vertex AI Gen AI Evaluation Service** | **Ragas / DeepEval** on Cloud Run; **AutoSxS** pairwise | Native groundedness + custom metrics, logs to Vertex Experiments/BigQuery. OSS libs give portable, framework-agnostic evals; AutoSxS for head-to-head model comparison. |
| Observability / tracing | **Cloud Trace + Cloud Logging + Cloud Monitoring**; Agent Engine traces | **OpenTelemetry → Cloud Trace**; **Langfuse** self-hosted on GKE | Unified, no extra infra, alerting built-in. OTel keeps you vendor-neutral; Langfuse if you want LLM-specific trace UX (still on GCP). |
| Metrics dashboard | **Looker Studio** over **BigQuery** | **Looker** (governed BI); **Grafana** on GKE | Looker Studio is free and fast for the demo scorecard. Looker for governed enterprise BI; Grafana if ops prefers it. |
| CI/CD | **Cloud Build** (triggers) + **Artifact Registry** | **Cloud Deploy** (progressive delivery); **GitHub Actions** + WIF | Cloud Build is native, runs the eval gate, deploys to Cloud Run/Agent Engine. Cloud Deploy adds canary/rollout pipelines; GitHub Actions via Workload Identity Federation if the team lives on GitHub. |
| Secrets | **Secret Manager** | **Cloud KMS** (key mgmt); Hashicorp Vault on GKE | Versioned secrets with IAM + audit; KMS for envelope encryption/CMEK; Vault only if mandated by existing tooling. |
| AuthN/Z | **IAM** + **Identity Platform** (end-user) + **Workload Identity** | **Cloud IAP** (zero-trust app access); API keys (low-trust) | IAM least-privilege + Workload Identity = no key files. Identity Platform for end-user sign-in; IAP to gate the demo UI without app-level auth. |
| Compute (default) | **Cloud Run** | **GKE Autopilot**; **Cloud Functions** (light) | Cloud Run = serverless containers, scale-to-zero, fast deploys. GKE for complex/stateful workloads & mesh; Functions for tiny event handlers. |
| Network security | **VPC Service Controls** perimeter | **Private Service Connect**; **VPC-SC + CMEK** combined | VPC-SC stops data exfiltration around Vertex + data services — the headline regulated-domain control. PSC for private endpoints to managed services. |
| PII protection | **Sensitive Data Protection (DLP) API** | Gemini-based redaction prompt; regex/Presidio on Cloud Run | DLP = managed, high-recall detection/redaction before model calls. Model/regex options for lighter or custom redaction needs. |

## 2. GCP-Native Architecture

```
   End user / Demo UI
        │  HTTPS
        ▼
  Cloud Load Balancing ─▶ API Gateway ─▶ ┌────────────────────────────┐
                                          │ Cloud Run: FastAPI service │  (stateless, autoscale)
                                          └───────────┬────────────────┘
                                  publish ClaimJob    │
                                                      ▼
                                                ┌──────────┐
                                                │ Pub/Sub  │
                                                └────┬─────┘
                                                     │ push/pull
                                          ┌──────────▼─────────────┐
                                          │ Cloud Run: Worker       │
                                          │  → invokes Agent Engine │
                                          └──────────┬─────────────┘
                                                     ▼
                            ┌────────────────────────────────────────────┐
                            │  Vertex AI Agent Engine (LangGraph runtime)  │
                            │  Supervisor + specialist agents              │
                            └─┬───────┬────────┬─────────┬────────┬───────┘
            Gemini 2.5 Pro/Flash     │        │         │        │
        ┌─────────────────┐   ┌──────▼───┐ ┌──▼────┐ ┌──▼─────┐ ┌▼──────────┐
        │ Document AI      │   │ Vertex   │ │ Vector│ │ MCP     │ │ Settlement│
        │ (intake/OCR)     │   │ Embedding│ │ Search│ │ servers │ │ rules     │
        └─────────────────┘   └──────────┘ └───────┘ │(Cloud   │ └───────────┘
                                                      │ Run)    │
                                                      └─────────┘
   State/Cache: Firestore (checkpoints) · Memorystore (cache)
   Data: Cloud SQL (audit) · GCS (docs) · BigQuery (metrics/eval)
   Cross-cutting: Cloud Trace/Logging/Monitoring · Gen AI Eval Service · Secret Manager · IAM
```

## 3. Layer-by-Layer Detail

### 3.1 Models — Vertex AI Gemini (model routing)
- **Gemini 2.5 Pro** for the coverage decision, compliance reasoning, and anything needing strong judgment.
- **Gemini 2.5 Flash** for extraction, query rewriting, routing — cheap and fast, the high-volume steps.
- Call via the **Vertex AI SDK** (`google-cloud-aiplatform` / `google-genai`), not the public Gemini API, so you get IAM, VPC-SC, data-residency, and enterprise controls. Talking point: *"Vertex keeps data in-tenant and in-region — that's why it's the right choice for regulated claims, not the consumer API."*
- **Structured output** via Gemini's controlled generation (response schema) → maps directly to your Pydantic contracts.

### 3.2 Intake — Document AI (new, strong)
FNOL forms and attachments go through **Document AI** (a Form Parser or a Custom Extractor processor) to produce structured fields before the Intake agent runs. This replaces the OCR/parser stub with a real Google service and makes the demo tangible (upload a PDF claim → structured `ClaimFacts`). Documents land in **GCS**; Document AI reads from there.

### 3.3 RAG — two valid Google paths (pick per scale)
- **Path A (build, more to show):** chunk policy/reg corpus → embed with `text-embedding-005` → index in **Vertex AI Vector Search** → retrieve → re-rank with **Vertex AI Ranking API** → ground with citations. Demonstrates you understand the pipeline.
- **Path B (managed):** **Vertex AI RAG Engine** or **Vertex AI Search** handles chunking, embedding, retrieval, and ranking as a managed corpus. Less code, very production-credible.
- **Recommendation:** build Path A for the policy corpus (shows depth), and mention RAG Engine as the "scale-up / less-ops" alternative. For the demo, AlloyDB/Cloud SQL `pgvector` is fine and cheaper than standing up Vector Search.

### 3.4 Orchestration — LangGraph on Vertex AI Agent Engine
- Keep your **LangGraph** state graph exactly as specified in the main spec.
- Deploy it to **Vertex AI Agent Engine** (the managed agent runtime — formerly Reasoning Engine), which natively supports LangGraph/LangChain. You get managed scaling, sessions, and built-in tracing without running your own orchestration servers.
- The Cloud Run worker invokes the deployed Agent Engine reasoning engine per claim. (Alternative: run LangGraph inside the Cloud Run worker directly if you want full control — both are GCP-native; Agent Engine is the more "managed" story.)
- **Checkpointer** → **Firestore** so human-in-the-loop claims can pause and resume.

### 3.5 Tools — MCP servers on Cloud Run
Each MCP server (`policy-db`, `claims-history`, `fraud-signals`, `regs`) is a small **Cloud Run** service, called by agents over authenticated HTTP. **Workload Identity** for service-to-service auth; **Secret Manager** for any credentials. Backing data in **Cloud SQL** / **BigQuery**.

### 3.6 Async & state
- **Pub/Sub** topic `claims.submitted` → worker subscription (push to Cloud Run). Dead-letter topic for poison messages. Autoscale workers on subscription backlog.
- **Memorystore for Redis** for semantic/response cache.

### 3.7 Evaluation — Vertex AI Gen AI Evaluation Service
- Replace Ragas with the **Gen AI Evaluation Service**: pointwise + pairwise metrics, built-in **groundedness**, coherence, safety, plus **custom metrics** (decision accuracy, citation correctness) via model-based or computation-based evaluators.
- Store the **golden dataset** in BigQuery/GCS; eval runs tracked in **Vertex AI Experiments**; results written to BigQuery.
- **CI gate** runs the eval job from **Cloud Build** on each PR; regression beyond tolerance fails the build.

### 3.8 Observability
- **Cloud Trace** for end-to-end latency spans across API → worker → Agent Engine → tools; **Agent Engine** emits agent step traces.
- **Cloud Logging** structured logs (every node's inputs/outputs/citations/cost/latency from the `trace` field).
- **Cloud Monitoring** dashboards + alerts (escalation rate, p95 latency, error rate, cost).
- **Looker Studio** over **BigQuery** for the business-facing scorecard (cost/claim, faithfulness over time) — the screenshot you bring to the interview.

### 3.9 Security & governance (Google-native)
- **IAM** least-privilege per service account; **Workload Identity** (no key files).
- **VPC Service Controls** perimeter around Vertex A