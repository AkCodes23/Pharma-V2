@description: Infrastructure parameters for Pharma Agentic AI

param location string = resourceGroup().location
param environmentName string = 'pharma-ai'

@secure()
param openAiApiKey string

// ── Cosmos DB (Serverless) ─────────────────────────────────
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: '${environmentName}-cosmos'
  location: location
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [{ name: 'EnableServerless' }]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location, failoverPriority: 0 }]
  }
}

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: 'pharma_agentic_ai'
  properties: { resource: { id: 'pharma_agentic_ai' } }
}

resource sessionsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDatabase
  name: 'sessions'
  properties: {
    resource: {
      id: 'sessions'
      partitionKey: { paths: ['/id'], kind: 'Hash' }
    }
  }
}

resource auditContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDatabase
  name: 'audit_trail'
  properties: {
    resource: {
      id: 'audit_trail'
      partitionKey: { paths: ['/session_id'], kind: 'Hash' }
      defaultTtl: 220752000  // 7 years in seconds
    }
  }
}

// ── Service Bus (Standard) ─────────────────────────────────
resource serviceBus 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: '${environmentName}-bus'
  location: location
  sku: { name: 'Standard', tier: 'Standard' }
}

resource legalTopic 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' = {
  parent: serviceBus
  name: 'legal-tasks'
  properties: { maxSizeInMegabytes: 1024 }
}

resource clinicalTopic 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' = {
  parent: serviceBus
  name: 'clinical-tasks'
  properties: { maxSizeInMegabytes: 1024 }
}

resource commercialTopic 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' = {
  parent: serviceBus
  name: 'commercial-tasks'
  properties: { maxSizeInMegabytes: 1024 }
}

resource socialTopic 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' = {
  parent: serviceBus
  name: 'social-tasks'
  properties: { maxSizeInMegabytes: 1024 }
}

resource knowledgeTopic 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' = {
  parent: serviceBus
  name: 'knowledge-tasks'
  properties: { maxSizeInMegabytes: 1024 }
}

// ── Key Vault ──────────────────────────────────────────────
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${environmentName}-kv'
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
  }
}

// ── Blob Storage ───────────────────────────────────────────
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: replace('${environmentName}storage', '-', '')
  location: location
  sku: { name: 'Standard_GRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource reportsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'reports'
}

// ── Container Apps Environment ─────────────────────────────
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${environmentName}-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 90 }
}

resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${environmentName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ── Outputs ────────────────────────────────────────────────
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output serviceBusEndpoint string = serviceBus.properties.serviceBusEndpoint
output keyVaultUri string = keyVault.properties.vaultUri
output storageAccountName string = storageAccount.name
output containerAppEnvId string = containerAppEnv.id
