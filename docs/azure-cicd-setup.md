# Azure CI/CD — one-time setup (keyless)

This wires GitHub Actions → Azure with **no stored secrets**. Two independent identities:

| Hop | Auth | Mechanism |
|---|---|---|
| Pipeline → Azure (deploy) | **OIDC federation** | GitHub's OIDC token, no client secret |
| App → Azure data/AI services (runtime) | **Managed identity** | Container App identity + RBAC; `DefaultAzureCredential` |

> Result: there are no API keys or client secrets anywhere in the repo, the pipeline, or the running app. This is why your Bicep sets `disableLocalAuth: true`. (API keys in a local `.env` are only for your laptop — never in CI or prod.)

The `cd.yml` workflow expects the names below. Run these once.

## 0. Prereqs
```bash
az login
az account set --subscription "<your-subscription-id>"
RG=rg-claimpilot-dev
ACR=cpacr$RANDOM            # must be globally unique, lowercase
API_APP=claimpilot-api
LOCATION=southindia
```

## 1. Registry + Container Apps environment (if not already from Bicep)
```bash
az acr create -g $RG -n $ACR --sku Basic
az containerapp env create -g $RG -n claimpilot-env -l $LOCATION
# First deploy can be a placeholder image; CD will replace it:
az containerapp create -g $RG -n $API_APP --environment claimpilot-env \
  --image mcr.microsoft.com/k8se/quickstart:latest --target-port 8000 --ingress external \
  --registry-server $ACR.azurecr.io --system-assigned
```

## 2. App → services: give the Container App's managed identity RBAC (keyless runtime)
```bash
APP_MI=$(az containerapp show -g $RG -n $API_APP --query identity.principalId -o tsv)
# Azure OpenAI
az role assignment create --assignee $APP_MI --role "Cognitive Services OpenAI User" \
  --scope $(az cognitiveservices account show -g $RG -n <aoai-name> --query id -o tsv)
# AI Search (data plane)
az role assignment create --assignee $APP_MI --role "Search Index Data Contributor" \
  --scope $(az search service show -g $RG -n <search-name> --query id -o tsv)
# Cosmos DB, Service Bus, Document Intelligence, App Insights → assign their
# respective data-plane roles to $APP_MI the same way.
```
With these in place the app uses `DefaultAzureCredential` (managed identity) — **delete the keys from `.env` for prod** and keep only `PROVIDER=azure` + the endpoint URLs.

## 3. Pipeline → Azure: OIDC federated credential (no client secret)
```bash
# App registration + service principal for the pipeline
APP_ID=$(az ad app create --display-name "claimpilot-github-oidc" --query appId -o tsv)
az ad sp create --id $APP_ID
# Federate it to THIS GitHub repo + branch (no secret is ever created)
az ad app federated-credential create --id $APP_ID --parameters '{
  "name": "claimpilot-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:alokranjan04/claimPilot:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'
# Let the pipeline push images and update the Container App
az role assignment create --assignee $APP_ID --role "AcrPush" \
  --scope $(az acr show -g $RG -n $ACR --query id -o tsv)
az role assignment create --assignee $APP_ID --role "Contributor" \
  --scope $(az group show -n $RG --query id -o tsv)   # scope tighter in real prod
```

## 4. Tell GitHub the IDs (these are identifiers, not secrets — but store as secrets/vars)
Repo → **Settings → Secrets and variables → Actions**:

**Secrets** (used by `azure/login`):
- `AZURE_CLIENT_ID` = `$APP_ID`
- `AZURE_TENANT_ID` = your tenant id (`az account show --query tenantId -o tsv`)
- `AZURE_SUBSCRIPTION_ID` = your subscription id

**Variables**:
- `ACR_NAME` = `$ACR`
- `AZURE_RG` = `$RG`
- `API_APP_NAME` = `$API_APP`
- (`WORKER_APP_NAME` if/when you split the worker)

## 5. Add the production environment gate (optional but recommended)
Repo → Settings → Environments → **production** → add yourself as a **required reviewer**. The `deploy` job (`environment: production`) then waits for a click before rolling out — a clean manual approval gate to talk about in interviews.

## 6. Ship it
Push to `main`. The pipeline: gate (ruff → mypy → pytest → **eval gate**) → `az acr build` → `az containerapp update`. Watch it in the repo's **Actions** tab; verify the new revision with the workflow's final step.

---

## Worker (scaling the background processor)
At M8 the worker runs in-process inside the API via the FastAPI lifespan, which is fine for the API + in-memory queue. For Service Bus-driven scale, deploy a **second Container App from the same image** with its own entrypoint command (a small `python -m claimpilot.api.worker`-style runner) and a KEDA Service Bus scale rule, then uncomment the worker block in `cd.yml`. Same image, same managed-identity auth — only the command and scale rule differ.

## Container Apps EasyAuth (AuthN/AuthZ — no code changes)

Enable Entra ID authentication on the Container App so `/v1/me` reads the
real user identity and roles instead of the debug fallback.

### a. Register the app in Entra ID
```bash
# Create the app registration
APP_REG_ID=$(az ad app create --display-name "ClaimPilot" --query appId -o tsv)

# Define the "admin" App Role (adjusters get the default role)
az ad app update --id $APP_REG_ID --app-roles '[{
  "allowedMemberTypes": ["User"],
  "displayName": "Admin",
  "description": "Can approve/deny escalated claims",
  "isEnabled": true,
  "value": "admin",
  "id": "'$(uuidgen)'"
}]'
```

### b. Enable EasyAuth on the Container App
```bash
az containerapp auth update -n claimpilot-api -g $RG \
  --unauthenticated-client-action AllowAnonymous \
  --enabled true

az containerapp auth microsoft update -n claimpilot-api -g $RG \
  --client-id $APP_REG_ID \
  --issuer "https://login.microsoftonline.com/$(az account show --query tenantId -o tsv)/v2.0" \
  --yes
```

### c. Assign the admin role to users
Azure Portal → Entra ID → Enterprise Applications → ClaimPilot →
Users and groups → Add → select user → assign "Admin" role.

### d. How it works (no code changes needed)
Container Apps EasyAuth injects these headers on every authenticated request:
- `X-MS-CLIENT-PRINCIPAL-NAME` → user's display name
- `X-MS-CLIENT-PRINCIPAL` → Base64-encoded JSON with claims including `roles`

The `get_caller()` dependency in `src/claimpilot/api/auth.py` reads these
headers automatically. When EasyAuth is disabled (local dev), it falls back
to the `X-Debug-Role` header (default: `adjuster`).

Routes protected with `require_role("admin")`:
- `POST /v1/claims/{id}/decision` — approve/deny escalated claims → 403 for non-admin
- `GET /v1/claims?status=escalated` — admin-only escalated claim queue → 403 for non-admin

---

## What to say in an interview
*"CI/CD is fully keyless: the pipeline authenticates to Azure with GitHub OIDC federation — no client secret stored — and the app authenticates to Azure OpenAI, AI Search, and Cosmos with the Container App's managed identity and RBAC, so there are no keys to rotate or leak. Every deploy re-runs the eval gate before rolling out a new Container Apps revision, with a manual approval gate on the production environment. AuthZ is role-based: the human-decision endpoint requires the `admin` App Role via Container Apps EasyAuth + Entra ID — no token-validation code, just a dependency that reads the EasyAuth headers."*
