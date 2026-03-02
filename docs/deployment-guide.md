# Pharma Agentic AI — Deployment Guide

## Prerequisites

- Azure CLI (`az`) v2.60+
- Azure subscription with Contributor access
- Docker + Azure Container Registry (ACR)
- Node.js 20+ (for frontend build)
- Python 3.11+ (for backend)

## 1. Infrastructure Provisioning

### 1.1 Deploy Azure Resources (Bicep)

```bash
# Login and set subscription
az login
az account set --subscription "<subscription-id>"

# Create resource group
az group create --name pharmaai-prod-rg --location eastus2

# Deploy all infrastructure
az deployment group create \
  --resource-group pharmaai-prod-rg \
  --template-file infra/bicep/main.bicep \
  --parameters environment=prod prefix=pharmaai imageTag=v1.0.0

# Capture outputs
az deployment group show \
  --resource-group pharmaai-prod-rg \
  --name main \
  --query properties.outputs
```

### 1.2 Seed Key Vault Secrets

```bash
KV_NAME="pharmaai-prod-kv"

# Azure OpenAI
az keyvault secret set --vault-name $KV_NAME --name azure-openai-api-key --value "<key>"
az keyvault secret set --vault-name $KV_NAME --name azure-openai-endpoint --value "<endpoint>"

# Cosmos DB
az keyvault secret set --vault-name $KV_NAME --name cosmos-db-key --value "<key>"
az keyvault secret set --vault-name $KV_NAME --name cosmos-db-endpoint --value "<endpoint>"

# Service Bus
az keyvault secret set --vault-name $KV_NAME --name service-bus-connection-string --value "<connstr>"

# Blob Storage
az keyvault secret set --vault-name $KV_NAME --name blob-storage-connection-string --value "<connstr>"

# AI Search
az keyvault secret set --vault-name $KV_NAME --name ai-search-api-key --value "<key>"
az keyvault secret set --vault-name $KV_NAME --name ai-search-endpoint --value "<endpoint>"

# Redis
az keyvault secret set --vault-name $KV_NAME --name redis-url --value "<url>"

# PostgreSQL
az keyvault secret set --vault-name $KV_NAME --name postgres-url --value "<url>"
```

## 2. Container Image Build & Push

```bash
ACR_NAME="pharmaaiprodcr"
az acr login --name $ACR_NAME

# Backend agents
for agent in planner supervisor executor; do
  docker build -t $ACR_NAME.azurecr.io/$agent:v1.0.0 -f docker/$agent.Dockerfile .
  docker push $ACR_NAME.azurecr.io/$agent:v1.0.0
done

# Frontend
docker build -t $ACR_NAME.azurecr.io/frontend:v1.0.0 -f docker/frontend.Dockerfile ./frontend
docker push $ACR_NAME.azurecr.io/frontend:v1.0.0
```

## 3. Verify Deployment

```bash
# Check Container App status
az containerapp show --name pharmaai-prod-planner --resource-group pharmaai-prod-rg --query "properties.runningStatus"

# Hit health endpoint
PLANNER_URL=$(az containerapp show --name pharmaai-prod-planner --resource-group pharmaai-prod-rg --query "properties.configuration.ingress.fqdn" -o tsv)
curl https://$PLANNER_URL/health

# Check logs
az containerapp logs show --name pharmaai-prod-planner --resource-group pharmaai-prod-rg --follow
```

## 4. Rollback

```bash
# Rollback to previous revision
az containerapp revision list --name pharmaai-prod-planner --resource-group pharmaai-prod-rg
az containerapp revision activate --name pharmaai-prod-planner --resource-group pharmaai-prod-rg --revision <previous-revision>
```

## 5. Environment-Specific Configuration

| Variable | Dev | Staging | Production |
|----------|-----|---------|------------|
| `APP_ENV` | development | staging | production |
| `KEY_VAULT_URL` | _(empty)_ | `https://pharmaai-staging-kv.vault.azure.net/` | `https://pharmaai-prod-kv.vault.azure.net/` |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | `https://staging.pharmaai.com` | `https://pharmaai.com` |
| Feature flags | All `false` | All `true` | All `true` |
