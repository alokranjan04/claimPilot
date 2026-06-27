# ClaimPilot — Deployment Runbook (M11)

Executable, ordered steps to deploy ClaimPilot to **Azure Container Apps** with a keyless **GitHub-OIDC CI/CD** pipeline. Run from the repo root in PowerShell with `az` logged in (`az login`) to the target subscription.

> Production auth target: **managed identity** (the providers fall back to `DefaultAzureCredential` when keys are empty). For the deployed app, prefer managed identity + RBAC over keys — steps 4–5 wire that. Keys in `.env` are for local dev only.

---

## 0. Variables
```powershell
$RG       = "rg-claimpilot"
$LOC      = "southindia"           # colocate with AOAI; AI Search/DocIntel may stay eastus
$ACR      = "claimpilotacr$((Get-Random))"   # globally unique, lowercase
$ENVNAME  = "claimpilot-env"
$APIAPP   = "claimpilot-api"
$WORKERAPP= "claimpilot-worker"
$AOAI     = "hindivoiceagent"
```

## 1. Resource group + Container Apps environment (Log Analytics-backed)
```powershell
az group create -n $RG -l $LOC
az containerapp env create -n $ENVNAME -g $RG -l $LOC   # creates Log Analytics workspace
```

## 2. Container registry
```powershell
az acr create -n $ACR -g $RG --sku Basic
```

## 3. Build the image in ACR (cloud build — no local Docker needed)
```powershell
az acr build --registry $ACR --image claimpilot:v1 .
```

## 4. Deploy the API as a Container App (system-assigned managed identity)
```powershell
az containerapp create -n $APIAPP -g $RG --environment $ENVNAME `
  --image "$ACR.azurecr.io/claimpilot:v1" `
  --target-port 8000 --ingress external `
  --registry-server "$ACR.azurecr.io" --system-assigned `
  --min-replicas 1 --max-replicas 5 `
  --env-vars PROVIDER=azure `
    AOAI_ENDPOINT=secretref:aoai-endpoint `
    AZURE_SEARCH_ENDPOINT=secretref:search-endpoint `
    AZURE_COSMOS_ENDPOINT=secretref:cosmos-endpoint `
    AZURE_SERVICEBUS_NAMESPACE=secretref:sb-namespace `
    AZURE_DOCINTEL_ENDPOINT=secretref:docintel-endpoint `
    AZURE_MONITOR_CONNECTION_STRING=secretref:appinsights-conn
# (add the endpoint values as Container App secrets: `az containerapp secret set ...`)
```

## 5. Grant the app's managed identity data-plane RBAC (keyless runtime)
```powershell
$MI = az containerapp show -n $APIAPP -g $RG --query identity.principalId -o tsv
# Azure OpenAI
az role assignment create --assignee $MI --role "Cognitive Services OpenAI User" `
  --scope $(az cognitiveservices account show -n $AOAI -g voiceAgent --query id -o tsv)
# AI Search (data plane)
az role assignment create --assignee $MI --role "Search Index Data Contributor" `
  --scope $(az search service show -n <search-name> -g <search-rg> --query id -o tsv)
# Cosmos, Service Bus, Document Intelligence → assign their data roles to $MI the same way.
```
> With RBAC in place, remove the key env-vars; the providers use `DefaultAzureCredential` (the app's managed identity). This is the production posture.

## 6. Deploy the Worker as a second Container App (same image, KEDA Service Bus scaler)
```powershell
az containerapp create -n $WORKERAPP -g $RG --environment $ENVNAME `
  --image "$ACR.azurecr.io/claimpilot:v1" `
  --registry-server "$ACR.azurecr.io" --system-assigned `
  --min-replicas 0 --max-replicas 10 `
  --command "python" "-m" "claimpilot.api.worker_main" `
  --env-vars PROVIDER=azure `
    AOAI_ENDPOINT=secretref:aoai-endpoint `
    AZURE_SEARCH_ENDPOINT=secretref:search-endpoint `
    AZURE_COSMOS_ENDPOINT=secretref:cosmos-endpoint `
    AZURE_SERVICEBUS_NAMESPACE=secretref:sb-namespace `
    AZURE_DOCINTEL_ENDPOINT=secretref:docintel-endpoint
# KEDA scale rule on Service Bus queue depth:
az containerapp update -n $WORKERAPP -g $RG `
  --scale-rule-name sb-queue --scale-rule-type azure-servicebus `
  --scale-rule-metadata "queueName=claims" "namespace=<sb-namespace>" "messageCount=5" `
  --scale-rule-auth "connection=service-bus-connection"
# repeat step 5 RBAC for the worker's managed identity
```

## 7. Ingest the policy corpus into Azure AI Search (one-time / re-index job)
The demo corpus is seeded in-memory at startup; for the deployed app, ingest it into the AI Search index so retrieval is backed by the managed service.
```powershell
# Set PROVIDER=azure env vars (or source .env), then:
uv run python -m claimpilot.rag.ingest_corpus
# Chunks the demo corpus, embeds via AOAI, upserts to AI Search index.
```

## 8. Wire CI/CD (keyless OIDC) — one-time
Follow `docs/azure-cicd-setup.md`:
- Create the federated credential + service principal.
- Assign `AcrPush` (registry) and `Contributor` (resource group) to the pipeline identity.
- Add GitHub **secrets** (`AZURE_CLIENT_ID/TENANT_ID/SUBSCRIPTION_ID`) and **variables** (`ACR_NAME`, `AZURE_RG`, `API_APP_NAME`, `WORKER_APP_NAME`).
- Add a required reviewer on the `production` environment for the manual approval gate.

Then every push to `main` runs: gate (ruff → mypy → pytest → **eval gate**) → `az acr build` → `az containerapp update` (canary revision).

## 9. Smoke test the live deployment
```powershell
$FQDN = az containerapp show -n $APIAPP -g $RG --query properties.configuration.ingress.fqdn -o tsv
curl.exe "https://$FQDN/healthz"
curl.exe -X POST "https://$FQDN/v1/claims" -H "content-type: application/json" `
  -d '{"policy_number":"POL-100","fnol_text":"Rear-ended in a parking lot at low speed. Minor bumper damage to insured vehicle. No injuries. Estimated repair cost $1800. Police report filed."}'
# poll GET https://$FQDN/v1/claims/{id} → expect auto_approved
```

## 10. Rollback (know this cold for the interview)
```powershell
az containerapp revision list -n $APIAPP -g $RG -o table
az containerapp ingress traffic set -n $APIAPP -g $RG --revision-weight <prev-revision>=100
```

## 11. Cost control
```powershell
# scale API to zero when idle (optional), and set a budget alert:
az consumption budget create --budget-name claimpilot --amount 50 --time-grain Monthly ...
# Tear down everything when done demoing:
az group delete -n $RG --yes --no-wait
```

---

### Status semantics for your repo
- **Implemented & deployable now:** image build, API Container App, ingress, CI/CD pipeline, smoke test, rollback.
- **Fast-follow (specified):** standalone worker app + KEDA scaler (needs a `worker_main` entrypoint), AI Search corpus-ingestion job, full managed-identity cutover (drop keys).
- See `docs/PRODUCTION_ARCHITECTURE.md` for the hardening design (network isolation, DR, SLOs, APIM, governance).
