// ClaimPilot — Azure baseline infrastructure
// Provisions the data/AI services required by the PROVIDER=azure stack.
// Azure OpenAI is NOT included — use your existing AOAI resource.
// Container Apps deployment (M11) is handled separately.
//
// Deploy:
//   az group create -n rg-claimpilot-dev -l southindia
//   az deployment group create \
//     -g rg-claimpilot-dev \
//     -f infra/iac/main.bicep \
//     -p @infra/iac/parameters.json \
//     -p location=southindia
//
// Resources created:
//   - Azure AI Search (Standard S1, semantic ranker enabled)
//   - Azure AI Document Intelligence (S0, in docIntelLocation)
//   - Azure Service Bus (Standard, single queue)
//   - Azure Cosmos DB (serverless, SQL API)
//   - Azure Monitor / Application Insights (Log Analytics workspace)
//   - Azure Key Vault (for secrets at runtime)
//
// NOT created (bring your own):
//   - Azure OpenAI — use existing resource, set AOAI_ENDPOINT + AOAI_API_KEY in .env
//
// Auth: Managed Identity is used everywhere — no connection strings in config.

@description('Short environment tag — appended to every resource name.')
@allowed(['dev', 'staging', 'prod'])
param environment string = 'dev'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Region for AI Search + Document Intelligence (semantic ranker not available in all regions).')
param aiServicesLocation string = 'centralindia'

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
// Azure AI Search (Standard S1 — required for semantic ranker)
// ---------------------------------------------------------------------------

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: '${prefix}-search-${uniqueSuffix}'
  location: aiServicesLocation  // semantic ranker not available in southindia
  sku: {
    name: 'standard'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    publicNetworkAccess: 'enabled'
    semanticSearch: 'standard'       // enables semantic ranker
  }
}

// ---------------------------------------------------------------------------
// Azure AI Document Intelligence (Form Recognizer)
// ---------------------------------------------------------------------------

resource docIntel 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' = {
  name: '${prefix}-docintel-${uniqueSuffix}'
  location: aiServicesLocation  // FormRecognizer unavailable in some regions (e.g. southindia)
  kind: 'FormRecognizer'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: '${prefix}-docintel-${uniqueSuffix}'
    publicNetworkAccess: 'enabled'
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
// Outputs (used by az CLI key-fetch commands and .env config)
// ---------------------------------------------------------------------------

@description('Azure AI Search endpoint — set as AZURE_SEARCH_ENDPOINT env var.')
output searchEndpoint string = 'https://${search.name}.search.windows.net'

@description('Azure AI Search resource name — use with az search admin-key show.')
output searchName string = search.name

@description('Document Intelligence endpoint — set as AZURE_DOCINTEL_ENDPOINT env var.')
output docIntelEndpoint string = docIntel.properties.endpoint

@description('Document Intelligence resource name — use with az cognitiveservices account keys list.')
output docIntelName string = docIntel.name

@description('Service Bus fully-qualified namespace — set as AZURE_SERVICEBUS_NAMESPACE env var.')
output serviceBusNamespaceFqdn string = '${serviceBusNamespace.name}.servicebus.windows.net'

@description('Service Bus namespace name — use with az servicebus namespace authorization-rule keys list.')
output serviceBusName string = serviceBusNamespace.name

@description('Cosmos DB endpoint — set as AZURE_COSMOS_ENDPOINT env var.')
output cosmosEndpoint string = cosmos.properties.documentEndpoint

@description('Cosmos DB account name — use with az cosmosdb keys list.')
output cosmosName string = cosmos.name

@description('Application Insights connection string — set as AZURE_MONITOR_CONNECTION_STRING env var.')
output appInsightsConnectionString string = appInsights.properties.ConnectionString

@description('Key Vault URI — store secrets here; reference via env / workload identity.')
output keyVaultUri string = keyVault.properties.vaultUri
