// ClaimPilot — Azure baseline infrastructure
// Provisions all data/AI services required by the PROVIDER=azure stack.
// Container Apps deployment (M11) is handled separately.
//
// Deploy:
//   az group create -n rg-claimpilot-dev -l eastus2
//   az deployment group create \
//     -g rg-claimpilot-dev \
//     -f infra/iac/main.bicep \
//     -p @infra/iac/parameters.json
//
// Resources created:
//   - Azure OpenAI (GPT-4o + text-embedding-3-small)
//   - Azure AI Search (Standard S1, semantic ranker enabled)
//   - Azure AI Document Intelligence (S0)
//   - Azure Service Bus (Standard, single queue)
//   - Azure Cosmos DB (serverless, SQL API)
//   - Azure Monitor / Application Insights (Log Analytics workspace)
//   - Azure Key Vault (for secrets at runtime)
//
// Auth: Managed Identity is used everywhere — no connection strings in config.
// Call `az role assignment create` (see outputs) after deployment.

@description('Short environment tag — appended to every resource name.')
@allowed(['dev', 'staging', 'prod'])
param environment string = 'dev'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('GPT-4o chat model deployment capacity (PTUs).')
param aoaiChatCapacity int = 10

@description('text-embedding-3-small deployment capacity (PTUs).')
param aoaiEmbeddingCapacity int = 10

@description('Embedding vector dimensions (must match application setting).')
param embeddingDimensions int = 1536

// ---------------------------------------------------------------------------
// Name tokens
// ---------------------------------------------------------------------------

var prefix = 'cp${environment}'
var uniqueSuffix = uniqueString(resourceGroup().id)

// ---------------------------------------------------------------------------
// Log Analytics Workspace (shared sink for all diagnostics)
// ---------------------------------------------------------------------------

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs-${uniqueSuffix}'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ---------------------------------------------------------------------------
// Application Insights (OTel → Azure Monitor exporter target)
// ---------------------------------------------------------------------------

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-ai-${uniqueSuffix}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ---------------------------------------------------------------------------
// Key Vault (for secrets — connection strings, API keys if any)
// ---------------------------------------------------------------------------

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${prefix}kv${uniqueSuffix}'
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true   // use RBAC, not access policies
    softDeleteRetentionInDays: 7
    enableSoftDelete: true
  }
}

// ---------------------------------------------------------------------------
// Azure OpenAI
// ---------------------------------------------------------------------------

resource aoai 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' = {
  name: '${prefix}-aoai-${uniqueSuffix}'
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: '${prefix}-aoai-${uniqueSuffix}'
    publicNetworkAccess: 'Enabled'   // restrict via Private Endpoint at prod
    disableLocalAuth: true           // Entra ID only — no API keys
  }
}

resource gpt4oDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-10-01-preview' = {
  parent: aoai
  name: 'gpt-4o'
  sku: {
    name: 'Standard'
    capacity: aoaiChatCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o'
      version: '2024-05-13'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-10-01-preview' = {
  parent: aoai
  name: 'text-embedding-3-small'
  dependsOn: [gpt4oDeployment]
  sku: {
    name: 'Standard'
    capacity: aoaiEmbeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
      version: '1'
    }
  }
}

// ---------------------------------------------------------------------------
// Azure AI Search (Standard S1 — required for semantic ranker)
// ---------------------------------------------------------------------------

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: '${prefix}-search-${uniqueSuffix}'
  location: location
  sku: {
    name: 'standard'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    publicNetworkAccess: 'Enabled'
    semanticSearch: 'standard'       // enables semantic ranker
    disableLocalAuth: true           // Entra ID only
  }
}

// ---------------------------------------------------------------------------
// Azure AI Document Intelligence (Form Recognizer)
// ---------------------------------------------------------------------------

resource docIntel 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' = {
  name: '${prefix}-docintel-${uniqueSuffix}'
  location: location
  kind: 'FormRecognizer'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: '${prefix}-docintel-${uniqueSuffix}'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

// ---------------------------------------------------------------------------
// Azure Service Bus (Standard tier — required for queues)
// ---------------------------------------------------------------------------

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: '${prefix}-sb-${uniqueSuffix}'
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {
    minimumTlsVersion: '1.2'
  }
}

resource claimsQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: serviceBusNamespace
  name: 'claims'
  properties: {
    maxDeliveryCount: 5
    defaultMessageTimeToLive: 'PT1H'   // 1-hour message TTL
    deadLetteringOnMessageExpiration: true
    lockDuration: 'PT5M'               // 5-min processing window per message
  }
}

// ---------------------------------------------------------------------------
// Azure Cosmos DB (Serverless — pay-per-request, ideal for checkpoints)
// ---------------------------------------------------------------------------

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2023-09-15' = {
  name: '${prefix}-cosmos-${uniqueSuffix}'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    disableLocalAuth: true             // Entra ID RBAC only
    minimalTlsVersion: 'Tls12'
  }
}

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-09-15' = {
  parent: cosmos
  name: 'claimpilot'
  properties: {
    resource: {
      id: 'claimpilot'
    }
  }
}

resource checkpointsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-09-15' = {
  parent: cosmosDatabase
  name: 'checkpoints'
  properties: {
    resource: {
      id: 'checkpoints'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
      defaultTtl: 86400              // auto-expire checkpoints after 24 h
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs (used by az role assignment create commands and app config)
// ---------------------------------------------------------------------------

@description('Azure OpenAI endpoint — set as AOAI_ENDPOINT env var.')
output aoaiEndpoint string = aoai.properties.endpoint

@description('Azure AI Search endpoint — set as AZURE_SEARCH_ENDPOINT env var.')
output searchEndpoint string = 'https://${search.name}.search.windows.net'

@description('Document Intelligence endpoint — set as AZURE_DOCINTEL_ENDPOINT env var.')
output docIntelEndpoint string = docIntel.properties.endpoint

@description('Service Bus fully-qualified namespace — set as AZURE_SERVICEBUS_NAMESPACE env var.')
output serviceBusNamespaceFqdn string = '${serviceBusNamespace.name}.servicebus.windows.net'

@description('Cosmos DB endpoint — set as AZURE_COSMOS_ENDPOINT env var.')
output cosmosEndpoint string = cosmos.properties.documentEndpoint

@description('Application Insights connection string — set as AZURE_MONITOR_CONNECTION_STRING env var.')
output appInsightsConnectionString string = appInsights.properties.ConnectionString

@description('Key Vault URI — store secrets here; reference via env / workload identity.')
output keyVaultUri string = keyVault.properties.vaultUri
