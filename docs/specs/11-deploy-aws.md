# ClaimPilot on AWS — Bedrock Native Deployment Spec
### Companion to ClaimPilot_Project_Spec.md · All-AWS stack

**Status:** Deployment Spec v1.0 · **Principle:** every component is a first-party AWS service. LangGraph remains the orchestration framework (open-source); it runs on **ECS Fargate** (or as **Bedrock Agents** if you prefer a fully managed agent runtime). The FastAPI surface, Pydantic contracts, LangGraph topology, and agent design from the main spec are unchanged — only implementations swap.

---

## 1. Component → AWS Service Mapping

Primary is what I'd build first; **Alternative(s)** is the in-AWS option I'd swap to under different scale/cost/control needs; **Why & key benefits** is the one-line defense for the interview.

| ClaimPilot component | **Primary (AWS) choice** | **Alternative(s) within AWS** | **Why this choice & key benefits** |
|---|---|---|---|
| LLM reasoning | **Amazon Bedrock — Claude (Anthropic)**: Sonnet for decisions, Haiku for extraction/routing | Bedrock **Llama / Mistral / Amazon Nova / Titan**; **SageMaker** self-hosted open model | Frontier quality with no infra, data stays in your account/region, IAM-governed. Two-tier routing = strong judgment on decisions, cheap on volume. Alternatives give model choice / cost control / full self-hosting. |
| Embeddings | **Bedrock — Titan Text Embeddings v2** | **Cohere Embed** on Bedrock; SageMaker-hosted embeddings | Managed, same security envelope as the LLM; Cohere for multilingual/quality; SageMaker when embeddings must be fully self-hosted. |
| Vector store / retrieval | **Amazon OpenSearch Serverless** (vector engine) | **Aurora PostgreSQL `pgvector`** (demo); **MemoryDB for Redis** (vector); Pinecone (Marketplace) | OpenSearch Serverless = low-latency hybrid (BM25 + vector) at scale, no cluster mgmt. Aurora pgvector keeps vectors beside transactional data (cheaper for demo). MemoryDB for ultra-low-latency. |
| Re-ranking | **Bedrock Rerank** (Cohere / Amazon Rerank) | self-hosted cross-encoder on SageMaker / ECS | Managed precision lift, no model to host; self-host only for a domain-tuned reranker. |
| Managed RAG | **Amazon Bedrock Knowledge Bases** | **Amazon Kendra** (enterprise search); fully hand-built pipeline | Knowledge Bases handles chunk/embed/retrieve/cite out of the box → fast to production with managed sync from S3. Kendra adds NLP search UX; hand-built shows depth + full grounding control. |
| Document intake / OCR | **Amazon Textract** (forms + tables) | **Bedrock multimodal** (Claude vision) for unstructured docs; **Rekognition** | Purpose-built for forms → structured fields + confidence scores; queries API for targeted extraction. Bedrock vision for messy/unstructured; Rekognition for image content. |
| Agent runtime | **LangGraph on ECS Fargate** | **Amazon Bedrock Agents** (native managed); **EKS**; **Lambda** (short tasks) | Fargate = serverless containers, full control of the graph, no node mgmt. Bedrock Agents if you want a managed agent loop; EKS for heavy/stateful; Lambda for light steps. |
| API gateway | **FastAPI on ECS Fargate** + **Amazon API Gateway** + **ALB** | **AWS App Runner** (simplest); **Lambda + API GW**; EKS ingress | Fargate scales cleanly and fronts well with API Gateway (auth, throttling, usage plans). App Runner for minimal ops; Lambda for spiky/low traffic. |
| Async queue | **Amazon SQS** (+ **SNS** fan-out) | **EventBridge** (event routing); **Amazon MSK** (Kafka); **Kinesis** (streaming) | SQS = simple, durable, dead-letter queues, autoscale workers on depth. SNS+SQS to fan out; EventBridge to wire S3/Textract events; MSK/Kinesis for high-throughput streaming. |
| Agent state / checkpoints | **Amazon DynamoDB** (LangGraph checkpointer) | **Aurora / RDS**; **ElastiCache** | DynamoDB = serverless, single-digit-ms, perfect for pause/resume human-in-the-loop. Aurora if state is relational; ElastiCache for ephemeral fast state. |
| Cache | **Amazon ElastiCache (Redis)** | **DynamoDB DAX**; in-process LRU | Sub-ms semantic/response cache cuts model cost & latency; DAX if caching DynamoDB reads; in-process when a managed cache isn't justified. |
| Audit log | **Aurora PostgreSQL** + **Athena/Redshift** (analytics) | **DynamoDB** append; **S3 + Athena** | Aurora = transactional, queryable, immutable audit trail; Athena/Redshift for analytics & dashboards. S3+Athena cheapest at scale; DynamoDB for high write. |
| Object storage | **Amazon S3** | — (canonical) | Durable, cheap, lifecycle rules, SSE-KMS, event triggers to Textract/Lambda. Standard for documents & artifacts. |
| Evaluation | **Amazon Bedrock Evaluations** (model + RAG eval, LLM-as-judge) | **Ragas / DeepEval** on Fargate; **SageMaker Clarify** | Native automated + human eval incl. RAG metrics, results to S3. OSS libs for portable, framework-agnostic evals; Clarify for bias/explainability. |
| Guardrails / safety | **Amazon Bedrock Guardrails** (PII, denied topics, **contextual grounding check**) | prompt-level guardrails; self-hosted filters | Managed, model-agnostic guardrails incl. a grounding/hallucination check tailor-made for RAG claims — a strong, defensible safety story. |
| Observability / tracing | **Amazon CloudWatch** (Logs/Metrics) + **AWS X-Ray** (tracing) + **Bedrock model invocation logging** | **OpenTelemetry → CloudWatch**; **Langfuse** on EKS | Unified, alerting built in, end-to-end traces across API→worker→Bedrock→tools. OTel keeps you vendor-neutral; Langfuse for LLM-specific trace UX. |
| Metrics dashboard | **Amazon QuickSight** over Athena/S3 | **Amazon Managed Grafana**; CloudWatch dashboards | QuickSight = quick business scorecard (cost/claim, faithfulness over time). Grafana if ops prefers it. |
| CI/CD | **AWS CodePipeline + CodeBuild** + **ECR** | **AWS CodeDeploy** (blue/green); **GitHub Actions** + OIDC | Native pipeline runs the eval gate and deploys to ECS/Bedrock. CodeDeploy for blue/green; GitHub Actions via OIDC if the team lives on GitHub. |
| Secrets | **AWS Secrets Manager** | **SSM Parameter Store**; **KMS** (keys) | Versioned secrets with rotation + IAM + audit; Parameter Store cheaper for config; KMS for envelope encryption / CMK. |
| AuthN/Z | **AWS IAM** + **Amazon Cognito** (end-user) + IAM roles (task roles / IRSA) | **API Gateway authorizers**; **Verified Permissions** (fine-grained) | IAM least-privilege + task roles = no static keys. Cognito for end-user sign-in; Verified Permissions for policy-based authz. |
| Compute (default) | **ECS Fargate** | **EKS**; **App Runner**; **Lambda**; EC2 | Fargate = serverless containers, no node mgmt, scales on demand. EKS for k8s/mesh; App Runner simplest; Lambda for event handlers. |
| Network security | **VPC + PrivateLink** (VPC endpoints for Bedrock/S3) + Security Groups | **AWS Network Firewall**; **AWS PrivateLink** everywhere | PrivateLink keeps Bedrock/S3 traffic off the public internet — the headline regulated-domain control. Network Firewall for deep packet/egress control. |
| PII protection | **Amazon Comprehend** (PII detection) + **Bedrock Guardrails** redaction | **Amazon Macie** (S3 PII discovery); regex/Presidio on Fargate | Comprehend + Guardrails redact PII before/within model calls; Macie continuously scans S3 for sensitive data at rest. |

## 2. AWS-Native Architecture

```
   End user / Demo UI
        │ HTTPS
        ▼
  CloudFront ─▶ Amazon API Gateway ─▶ ┌──────────────────────────────┐
                                       │ ECS Fargate: FastAPI service │ (stateless, autoscale)
                                       └──────────────┬───────────────┘
                                 publish ClaimJob     │
                                                      ▼
                                                ┌──────────┐   DLQ
                                                │   SQS    │───────▶ (dead-letter)
                                                └────┬─────┘
                                                     ▼
                                          ┌────────────────────────┐
                                          │ ECS Fargate: Worker     │
                                          │  runs LangGraph graph   │
                                          └──────────┬─────────────┘
                                                     ▼
                  ┌──────────────────────────────────────────────────────┐
                  │  Supervisor + specialist agents (LangGraph)            │
                  └─┬─────────┬──────────┬──────────┬──────────┬──────────┘
   Bedrock Claude   │         │          │          │          │
   (Sonnet/Haiku) ──┘  ┌──────▼─────┐ ┌──▼───────┐ ┌▼────────┐ ┌▼──────────┐
                       │ Textract   │ │ Titan    │ │OpenSearch│ │ MCP servers│
                       │ (intake)   │ │ Embed    │ │Serverless│ │ (Fargate) │
                       └────────────┘ └──────────┘ └──────────┘ └───────────┘
   + Bedrock Guardrails on every model call
   State/Cache: DynamoDB (checkpoints) · ElastiCache (cache)
   Data: Aurora (audit) · S3 (docs) · Athena/QuickSight (metrics)
   Cross-cutting: CloudWatch + X-Ray · Bedrock Evaluations · Secrets Manager · IAM · PrivateLink
```

## 3. Layer-by-Layer Detail

### 3.1 Models — Amazon Bedrock (model routing)
- **Claude Sonnet** for coverage decisions & compliance reasoning; **Claude Haiku** for extraction, routing, query rewriting (cheap, fast, high volume).
- Call via the **Bedrock Runtime API** (`bedrock-runtime` / Converse API) — data stays in your AWS account and region, IAM-governed, with **VPC endpoints** so traffic never hits the public internet.
- Structured output via the **Converse API tool-use / JSON schema** → maps to your Pydantic contracts.
- Wrap every invocation in a **Bedrock Guardrail** (PII filter + contextual grounding check).

### 3.2 Intake — Amazon Textract
FNOL forms/attachments land in **S3** → **Textract** (AnalyzeDocument / Queries) extracts structured fields + tables with confidence scores before the Intake agent runs. An **S3 event** can trigger a Lambda to kick off processing. Big demo win: upload a PDF claim → structured `ClaimFacts`.

### 3.3 RAG — two valid AWS paths
- **Path A (build, more to show):** chunk corpus → embed with Titan v2 → index in **OpenSearch Serverless** → hybrid retrieve → **Bedrock Rerank** → ground with citations.
- **Path B (managed):** **Bedrock Knowledge Bases** points at an S3 corpus and handles chunk/embed/retrieve/cite, with managed sync.
- **Recommendation:** build Path A for the policy corpus (depth) and mention Knowledge Bases as the managed scale-up. For the cheapest demo, Aurora `pgvector` is fine.

### 3.4 Orchestration — LangGraph on ECS Fargate
- Keep the LangGraph state graph from the main spec; run it in a **Fargate** worker triggered off SQS.
- **Checkpointer → DynamoDB** so human-in-the-loop claims pause/resume.
- Alternative managed story: **Bedrock Agents** with action groups (Lambda-backed tools) and a Knowledge Base — mention as the "fully managed agent runtime" option.

### 3.5 Tools — MCP servers on Fargate/App Runner
Each MCP server (`policy-db`, `claims-history`, `fraud-signals`, `regs`) is a small **Fargate/App Runner** service over authenticated HTTP; **IAM task roles** for service-to-service auth; **Secrets Manager** for credentials; backing data in **Aurora/DynamoDB**.

### 3.6 Async & state
- **SQS** `claims-submitted` (+ DLQ) drives Fargate workers; autoscale on `ApproximateNumberOfMessages`. **SNS** if you need fan-out; **EventBridge** to wire S3/Textract events.
- **ElastiCache (Redis)** for semantic/response cache.

### 3.7 Evaluation — Amazon Bedrock Evaluations
- Replace Ragas with **Bedrock Evaluations**: automatic (LLM-as-judge) + human eval, including **RAG/retrieval metrics** and custom prompt datasets in S3.
- Golden dataset in S3; results to S3/Athena; **CI gate** runs the eval job from **CodeBuild** and fails on regression beyond tolerance.

### 3.8 Observability
- **CloudWatch Logs** (structured per-node trace), **CloudWatch Metrics** + alarms (escalation rate, p95 latency, cost, errors), **X-Ray** end-to-end spans, and **Bedrock model invocation logging** to S3/CloudWatch.
- **QuickSight** over Athena for the business scorecard screenshot.

### 3.9 Security & governance
- **IAM** least-privilege + ECS **task roles** (no static keys); **Cognito** for end-user auth.
- **PrivateLink / VPC endpoints** for Bedrock, S3, etc.; private subnets; Security Groups.
- **Secrets Manager** (+ rotation); **KMS CMK** on S3/Aurora/DynamoDB.
- **Bedrock Guardrails** + **Comprehend** PII redaction; **Macie** for S3 PII discovery.
- Immutable audit in Aurora; **CloudTrail** for control-plane/data-access audit.

## 4. CI/CD & IaC (all AWS)
- **Source** → CodeCommit or GitHub; **CodePipeline** orchestrates **CodeBuild** stages: lint (ruff) → type-check (mypy) → unit tests → build container → push to **ECR** → **run Bedrock eval job (gate)** → deploy to ECS (blue/green via **CodeDeploy**).
- **IaC:** **AWS CDK** (Python) or **Terraform** provisions Bedrock access, ECS/Fargate, SQS, DynamoDB, Aurora, OpenSearch, IAM, Secrets Manager, S3. Keep in `infra/`.
- **Safe rollout:** ECS blue/green or canary with instant rollback — your safe-rollout story, natively.

```
infra/
├── cdk/                       # or terraform/  (Bedrock, ECS, SQS, DynamoDB, OpenSearch, Aurora, IAM...)
├── buildspec.yml              # CodeBuild incl. eval gate
└── Dockerfile(s)
```

## 5. Cost & Footprint Notes (for the demo)
- Use **Claude Haiku** for all but the final decision; route to **Sonnet** only on decision/compliance nodes.
- For the demo prefer **Aurora `pgvector`** (or OpenSearch Serverless min capacity) over a large OpenSearch index — OpenSearch Serverless has minimum OCU cost.
- **Fargate + SQS** scale down to near-zero between demos (no scale-to-zero like Lambda, but min tasks = 0/1).
- Textract and Bedrock Evaluations are pay-per-use — fine for a portfolio footprint.
- Set an **AWS Budget + alert**; mention it — cost-awareness is a senior signal.

## 6. What Changes in the Codebase vs. the Generic Spec
- `infra/llm/` → Bedrock client (Converse API), model-router Sonnet vs Haiku, Guardrail attached.
- `rag/` → Titan embeddings + OpenSearch Serverless (or pgvector) + Bedrock Rerank.
- `agents/intake` → Textract client.
- `graph/` checkpointer → DynamoDB.
- `infra/queue/` → SQS publisher/consumer (+ DLQ).
- `evals/` → Bedrock Evaluations jobs.
- `observability/` → OpenTelemetry → X-Ray + CloudWatch structured logging.
- CI → `buildspec.yml` + CodePipeline; add `infra/cdk` (or terraform).
- Unchanged: FastAPI surface, Pydantic contracts, LangGraph topology, agent design.

## 7. Interview Talking Points (AWS-native)
- *"Why Bedrock over a public API?"* → data stays in-account/in-region, IAM + PrivateLink, choice of Claude/Llama/Nova, managed Guardrails — the controls a regulated claims workload needs.
- *"How do you orchestrate?"* → LangGraph state machine on Fargate (or Bedrock Agents) — my graph logic intact, serverless containers.
- *"Cheap and fast?"* → Claude Haiku for volume, Sonnet for decisions; ElastiCache semantic cache; Fargate autoscale on SQS depth.
- *"Evaluate & gate releases?"* → Bedrock Evaluations (RAG + custom metrics) as a CodeBuild gate; results in S3/Athena.
- *"Secure?"* → IAM least-privilege, task roles, PrivateLink, Guardrails + Comprehend/Macie PII, KMS, CloudTrail.
- *"Scale to 10k claims/day?"* → SQS-driven Fargate autoscaling, DynamoDB checkpoints, OpenSearch Serverless index.

## 8. Build Order Delta (AWS-specific)
1. **Account setup:** enable Bedrock model access (Claude/Titan), create VPC + endpoints, IAM roles, CDK/Terraform baseline.
2. **Bedrock wiring:** Converse client + model router; Titan embeddings + OpenSearch/pgvector; smoke-test a grounded RAG answer + Guardrail.
3. **Textract → SQS → Fargate worker → LangGraph** end-to-end on a fake claim; DynamoDB checkpoints.
4. **Bedrock Evaluations + CodeBuild gate**, then CloudWatch alarms + QuickSight dashboard.

> Note: AWS evolves Bedrock fast (new models, Rerank, Guardrails features, Knowledge Bases options). Confirm current model IDs, region availability, and quotas in the Bedrock console when you start — the architecture and service roles are what matter.
