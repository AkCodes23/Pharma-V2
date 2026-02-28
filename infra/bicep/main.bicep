// Pharma Agentic AI — Azure Infrastructure (Bicep)
// Provisions all Azure resources for the platform.

@description('Environment name (dev, staging, prod)')
param environment string = 'prod'

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Unique project prefix')
param prefix string = 'pharmaai'

var resourceSuffix = '${prefix}-${environment}'

// ── Azure OpenAI ─────────────────────────────────────────
resource openai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: '${resourceSuffix}-openai'
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: '${resourceSuffix}-openai'
    publicNetworkAccess: 'Enabled'
  }
}

resource gpt4oDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: 'gpt-4o'
  sku: {
    name: 'Standard'
    capacity: 80
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o'
      version: '2024-11-20'
    }
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: 'text-embedding-3-small'
  sku: {
    name: 'Standard'
    capacity: 120
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
      version: '1'
    }
  }
}

// ── Cosmos DB (NoSQL + Gremlin) ──────────────────────────
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: '${resourceSuffix}-cosmos'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    capabilities: [
      { name: 'EnableGremlin' }
    ]
    locations: [
      {
        locationName: location
        failoverPriority: 0
      }
    ]
  }
}

resource cosmosNoSQLDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: 'pharma_agentic_ai'
  properties: {
    resource: {
      id: 'pharma_agentic_ai'
    }
  }
}

resource sessionsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosNoSQLDb
  name: 'sessions'
  properties: {
    resource: {
      id: 'sessions'
      partitionKey: {
        paths: ['/session_id']
        kind: 'Hash'
      }
      defaultTtl: -1
    }
    options: {
      autoscaleSettings: {
        maxThroughput: 4000
      }
    }
  }
}

resource auditContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosNoSQLDb
  name: 'audit_trail'
  properties: {
    resource: {
      id: 'audit_trail'
      partitionKey: {
        paths: ['/session_id']
        kind: 'Hash'
      }
      defaultTtl: -1
    }
    options: {
      autoscaleSettings: {
        maxThroughput: 4000
      }
    }
  }
}

// ── Service Bus ──────────────────────────────────────────
resource serviceBus 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: '${resourceSuffix}-bus'
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
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

// ── Azure AI Search ──────────────────────────────────────
resource aiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' = {
  name: '${resourceSuffix}-search'
  location: location
  sku: {
    name: 'standard'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    semanticSearch: 'standard'
  }
}

// ── Azure Cache for Redis ────────────────────────────────
resource redis 'Microsoft.Cache/redis@2024-03-01' = {
  name: '${resourceSuffix}-redis'
  location: location
  properties: {
    sku: {
      name: 'Standard'
      family: 'C'
      capacity: 1
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
  }
}

// ── Azure DB for PostgreSQL ──────────────────────────────
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${resourceSuffix}-pg'
  location: location
  sku: {
    name: 'Standard_B2ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    storage: {
      storageSizeGB: 32
    }
    highAvailability: {
      mode: 'Disabled'
    }
  }
}

// ── Blob Storage ─────────────────────────────────────────
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: replace('${prefix}${environment}sa', '-', '')
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

// ── Key Vault ────────────────────────────────────────────
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${resourceSuffix}-kv'
  location: location
  properties: {
    sku: {
      name: 'standard'
      family: 'A'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
  }
}

// ── Azure AI Language (NER) ──────────────────────────────
resource aiLanguage 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: '${resourceSuffix}-language'
  location: location
  kind: 'TextAnalytics'
  sku: {
    name: 'S'
  }
  properties: {
    customSubDomainName: '${resourceSuffix}-language'
    publicNetworkAccess: 'Enabled'
  }
}

// ── Azure Web PubSub ─────────────────────────────────────
resource webPubSub 'Microsoft.SignalRService/webPubSub@2024-03-01' = {
  name: '${resourceSuffix}-pubsub'
  location: location
  sku: {
    name: 'Standard_S1'
    capacity: 1
  }
  properties: {}
}

// ── Application Insights ─────────────────────────────────
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${resourceSuffix}-insights'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    IngestionMode: 'LogAnalytics'
  }
}

// ── Outputs ──────────────────────────────────────────────
output openaiEndpoint string = openai.properties.endpoint
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output searchEndpoint string = 'https://${aiSearch.name}.search.windows.net'
output redisHostname string = redis.properties.hostName
output postgresHostname string = postgres.properties.fullyQualifiedDomainName
output aiLanguageEndpoint string = aiLanguage.properties.endpoint
output webPubSubHostname string = webPubSub.properties.hostName
output appInsightsConnectionString string = appInsights.properties.ConnectionString
