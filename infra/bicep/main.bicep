// ============================================================
// Pharma Agentic AI — Consolidated Azure Infrastructure (Bicep)
// ============================================================
// Single source of truth for ALL Azure resources.
// Provisions: OpenAI, Cosmos DB, Service Bus (with subscriptions),
// Event Hubs, AI Search, Redis, PostgreSQL, Blob Storage,
// Key Vault, Managed Identity + RBAC, AI Language, Web PubSub,
// Log Analytics, Application Insights, Container Apps Environment,
// and all Container App definitions.
//
// WHY consolidated: Previously split across infra/main.bicep
// and infra/bicep/main.bicep with conflicting definitions.
// This file merges both and adds missing resources.
// ============================================================

// ── Parameters ───────────────────────────────────────────────
@description('Environment name (dev, staging, prod)')
param environment string = 'prod'

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Unique project prefix')
param prefix string = 'pharmaai'

@description('Container image tag for deployments')
param imageTag string = 'latest'

@description('Container registry login server')
param containerRegistryServer string = '${prefix}${environment}cr.azurecr.io'

var resourceSuffix = '${prefix}-${environment}'
var tags = {
  project: 'pharma-agentic-ai'
  environment: environment
  managedBy: 'bicep'
}

// ============================================================
// 1. MANAGED IDENTITY + RBAC
// ============================================================

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${resourceSuffix}-identity'
  location: location
  tags: tags
}

// ============================================================
// 2. LOG ANALYTICS + APPLICATION INSIGHTS
// ============================================================

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${resourceSuffix}-logs'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 90
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${resourceSuffix}-insights'
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    IngestionMode: 'LogAnalytics'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ============================================================
// 3. AZURE OPENAI
// ============================================================

resource openai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: '${resourceSuffix}-openai'
  location: location
  kind: 'OpenAI'
  tags: tags
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: '${resourceSuffix}-openai'
    publicNetworkAccess: 'Enabled'
  }
}

resource gpt4oDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: 'gpt-4o'
  sku: { name: 'Standard'; capacity: 80 }
  properties: {
    model: { format: 'OpenAI'; name: 'gpt-4o'; version: '2024-11-20' }
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: 'text-embedding-3-small'
  sku: { name: 'Standard'; capacity: 120 }
  properties: {
    model: { format: 'OpenAI'; name: 'text-embedding-3-small'; version: '1' }
  }
  dependsOn: [gpt4oDeployment]
}

// ============================================================
// 4. COSMOS DB (NoSQL + Gremlin)
// ============================================================

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: '${resourceSuffix}-cosmos'
  location: location
  kind: 'GlobalDocumentDB'
  tags: tags
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    capabilities: [{ name: 'EnableGremlin' }]
    locations: [{ locationName: location; failoverPriority: 0 }]
  }
}

resource cosmosNoSQLDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: 'pharma_agentic_ai'
  properties: { resource: { id: 'pharma_agentic_ai' } }
}

resource sessionsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosNoSQLDb
  name: 'sessions'
  properties: {
    resource: {
      id: 'sessions'
      partitionKey: { paths: ['/session_id']; kind: 'Hash' }
      defaultTtl: -1
    }
    options: { autoscaleSettings: { maxThroughput: 4000 } }
  }
}

resource auditContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosNoSQLDb
  name: 'audit_trail'
  properties: {
    resource: {
      id: 'audit_trail'
      partitionKey: { paths: ['/session_id']; kind: 'Hash' }
      defaultTtl: 220752000  // 7 years retention
    }
    options: { autoscaleSettings: { maxThroughput: 4000 } }
  }
}

// RBAC: Cosmos DB Data Contributor for Managed Identity
resource cosmosRbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cosmosAccount.id, managedIdentity.id, 'cosmos-contributor')
  scope: cosmosAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '00000000-0000-0000-0000-000000000002')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ============================================================
// 5. SERVICE BUS (with subscriptions)
// ============================================================

resource serviceBus 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: '${resourceSuffix}-bus'
  location: location
  tags: tags
  sku: { name: 'Standard'; tier: 'Standard' }
}

var topicNames = ['legal-tasks', 'clinical-tasks', 'commercial-tasks', 'social-tasks', 'knowledge-tasks', 'news-tasks']

resource topics 'Microsoft.ServiceBus/namespaces/topics@2024-01-01' = [for name in topicNames: {
  parent: serviceBus
  name: name
  properties: {
    maxSizeInMegabytes: 1024
    defaultMessageTimeToLive: 'PT1H'
  }
}]

// Subscriptions — one per retriever agent per topic
resource legalSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[0]
  name: 'retriever-legal-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

resource clinicalSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[1]
  name: 'retriever-clinical-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

resource commercialSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[2]
  name: 'retriever-commercial-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

resource socialSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[3]
  name: 'retriever-social-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

resource knowledgeSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[4]
  name: 'retriever-knowledge-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

resource newsSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[5]
  name: 'retriever-news-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

// DLQ monitoring subscriptions — one per topic
resource legalDlqSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[0]
  name: 'retriever-legal-dlq-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

resource clinicalDlqSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[1]
  name: 'retriever-clinical-dlq-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

resource commercialDlqSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[2]
  name: 'retriever-commercial-dlq-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

resource socialDlqSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[3]
  name: 'retriever-social-dlq-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

resource knowledgeDlqSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[4]
  name: 'retriever-knowledge-dlq-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

resource newsDlqSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
  parent: topics[5]
  name: 'retriever-news-dlq-sub'
  properties: { lockDuration: 'PT1M'; maxDeliveryCount: 5; deadLetteringOnMessageExpiration: true }
}

// RBAC: Service Bus Data Sender + Receiver for Managed Identity
resource sbSenderRbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBus.id, managedIdentity.id, 'sb-sender')
  scope: serviceBus
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource sbReceiverRbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBus.id, managedIdentity.id, 'sb-receiver')
  scope: serviceBus
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ============================================================
// 6. EVENT HUBS (for KEDA scaling)
// ============================================================

resource eventHubsNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: '${resourceSuffix}-events'
  location: location
  tags: tags
  sku: { name: 'Standard'; tier: 'Standard'; capacity: 1 }
}

var eventHubNames = ['pharma.tasks.legal', 'pharma.tasks.clinical', 'pharma.tasks.news']

resource eventHubs 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = [for name in eventHubNames: {
  parent: eventHubsNamespace
  name: name
  properties: {
    partitionCount: 4
    messageRetentionInDays: 1
  }
}]

resource kedaCheckpointStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: replace('${prefix}${environment}keda', '-', '')
  location: location
  kind: 'StorageV2'
  tags: tags
  sku: { name: 'Standard_LRS' }
  properties: { minimumTlsVersion: 'TLS1_2' }
}

// ============================================================
// 7. AI SEARCH
// ============================================================

resource aiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' = {
  name: '${resourceSuffix}-search'
  location: location
  tags: tags
  sku: { name: 'standard' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    semanticSearch: 'standard'
  }
}

// ============================================================
// 8. REDIS
// ============================================================

resource redis 'Microsoft.Cache/redis@2024-03-01' = {
  name: '${resourceSuffix}-redis'
  location: location
  tags: tags
  properties: {
    sku: { name: 'Standard'; family: 'C'; capacity: 1 }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
  }
}

// ============================================================
// 9. POSTGRESQL
// ============================================================

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${resourceSuffix}-pg'
  location: location
  tags: tags
  sku: { name: 'Standard_B2ms'; tier: 'Burstable' }
  properties: {
    version: '16'
    storage: { storageSizeGB: 32 }
    highAvailability: { mode: 'Disabled' }
    authConfig: { activeDirectoryAuth: 'Enabled'; passwordAuth: 'Disabled' }
  }
}

// ============================================================
// 10. BLOB STORAGE
// ============================================================

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: replace('${prefix}${environment}sa', '-', '')
  location: location
  kind: 'StorageV2'
  tags: tags
  sku: { name: 'Standard_GRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource reportsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'reports'
}

// RBAC: Storage Blob Data Contributor
resource storageRbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, managedIdentity.id, 'storage-contributor')
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ============================================================
// 11. KEY VAULT
// ============================================================

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${resourceSuffix}-kv'
  location: location
  tags: tags
  properties: {
    sku: { name: 'standard'; family: 'A' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
  }
}

// RBAC: Key Vault Secrets User for Managed Identity
resource kvRbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, managedIdentity.id, 'kv-secrets-user')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ============================================================
// 12. AI LANGUAGE (NER)
// ============================================================

resource aiLanguage 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: '${resourceSuffix}-language'
  location: location
  kind: 'TextAnalytics'
  tags: tags
  sku: { name: 'S' }
  properties: {
    customSubDomainName: '${resourceSuffix}-language'
    publicNetworkAccess: 'Enabled'
  }
}

// ============================================================
// 13. WEB PUBSUB
// ============================================================

resource webPubSub 'Microsoft.SignalRService/webPubSub@2024-03-01' = {
  name: '${resourceSuffix}-pubsub'
  location: location
  tags: tags
  sku: { name: 'Standard_S1'; capacity: 1 }
  properties: {}
}

// ============================================================
// 14. CONTAINER APPS ENVIRONMENT
// ============================================================

resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${resourceSuffix}-env'
  location: location
  tags: tags
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

// ── Container App: Planner ───────────────────────────────────
resource plannerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${resourceSuffix}-planner'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${managedIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: { external: true; targetPort: 8000; transport: 'auto' }
      registries: [{ server: containerRegistryServer; identity: managedIdentity.id }]
    }
    template: {
      containers: [{
        name: 'planner'
        image: '${containerRegistryServer}/planner:${imageTag}'
        resources: { cpu: json('0.5'); memory: '1Gi' }
        env: [
          { name: 'APP_ENV'; value: environment }
          { name: 'KEY_VAULT_URL'; value: keyVault.properties.vaultUri }
          { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'; value: appInsights.properties.ConnectionString }
        ]
      }]
      scale: { minReplicas: 1; maxReplicas: 10 }
    }
  }
}

// ── Container App: Supervisor ────────────────────────────────
resource supervisorApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${resourceSuffix}-supervisor'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${managedIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      registries: [{ server: containerRegistryServer; identity: managedIdentity.id }]
    }
    template: {
      containers: [{
        name: 'supervisor'
        image: '${containerRegistryServer}/supervisor:${imageTag}'
        resources: { cpu: json('0.5'); memory: '1Gi' }
        env: [
          { name: 'APP_ENV'; value: environment }
          { name: 'KEY_VAULT_URL'; value: keyVault.properties.vaultUri }
        ]
      }]
      scale: { minReplicas: 1; maxReplicas: 5 }
    }
  }
}

// ── Container App: Executor ──────────────────────────────────
resource executorApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${resourceSuffix}-executor'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${managedIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      registries: [{ server: containerRegistryServer; identity: managedIdentity.id }]
    }
    template: {
      containers: [{
        name: 'executor'
        image: '${containerRegistryServer}/executor:${imageTag}'
        resources: { cpu: json('1.0'); memory: '2Gi' }
        env: [
          { name: 'APP_ENV'; value: environment }
          { name: 'KEY_VAULT_URL'; value: keyVault.properties.vaultUri }
        ]
      }]
      scale: { minReplicas: 1; maxReplicas: 5 }
    }
  }
}

// ── Container App: Frontend ──────────────────────────────────
resource frontendApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${resourceSuffix}-frontend'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${managedIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: { external: true; targetPort: 3000; transport: 'auto' }
      registries: [{ server: containerRegistryServer; identity: managedIdentity.id }]
    }
    template: {
      containers: [{
        name: 'frontend'
        image: '${containerRegistryServer}/frontend:${imageTag}'
        resources: { cpu: json('0.25'); memory: '512Mi' }
        env: [
          { name: 'NEXT_PUBLIC_API_URL'; value: 'https://${resourceSuffix}-planner.${containerAppEnv.properties.defaultDomain}' }
        ]
      }]
      scale: { minReplicas: 1; maxReplicas: 5 }
    }
  }
}

// ============================================================
// OUTPUTS
// ============================================================

output openaiEndpoint string = openai.properties.endpoint
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output searchEndpoint string = 'https://${aiSearch.name}.search.windows.net'
output redisHostname string = redis.properties.hostName
output postgresHostname string = postgres.properties.fullyQualifiedDomainName
output serviceBusEndpoint string = serviceBus.properties.serviceBusEndpoint
output keyVaultUri string = keyVault.properties.vaultUri
output storageAccountName string = storage.name
output aiLanguageEndpoint string = aiLanguage.properties.endpoint
output webPubSubHostname string = webPubSub.properties.hostName
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output containerAppEnvId string = containerAppEnv.id
output managedIdentityClientId string = managedIdentity.properties.clientId
output plannerUrl string = plannerApp.properties.configuration.ingress.fqdn
output frontendUrl string = frontendApp.properties.configuration.ingress.fqdn
