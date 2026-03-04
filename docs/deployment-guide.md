# Deployment Guide

This document describes how to deploy the stack to Azure and how to verify runtime correctness.

## 1. Deployment Architecture

Provisioned from `infra/bicep/main.bicep`:
- Managed identity
- Log Analytics + App Insights
- Azure OpenAI deployments
- Cosmos DB (NoSQL + Gremlin capability)
- Service Bus namespace with topics/subscriptions
- Event Hubs
- AI Search
- Redis
- PostgreSQL
- Storage account + reports container
- Key Vault
- Container Apps environment and app resources

## 2. Prerequisites

- Azure CLI logged in
- Subscription + resource group permissions
- Bicep support in CLI
- Container registry access

## 3. Resource Group and Bicep Deployment

```bash
az login
az account set --subscription <subscription-id>
az group create --name <rg-name> --location <region>

az deployment group create \
  --resource-group <rg-name> \
  --template-file infra/bicep/main.bicep \
  --parameters environment=prod prefix=pharmaai imageTag=latest
```

Capture outputs:

```bash
az deployment group show \
  --resource-group <rg-name> \
  --name <deployment-name> \
  --query properties.outputs
```

## 4. Message Bus Provisioning Verification

Verify topics:
- `legal-tasks`
- `clinical-tasks`
- `commercial-tasks`
- `social-tasks`
- `knowledge-tasks`
- `news-tasks`

Verify retriever subscriptions:
- `retriever-legal-sub`
- `retriever-clinical-sub`
- `retriever-commercial-sub`
- `retriever-social-sub`
- `retriever-knowledge-sub`
- `retriever-news-sub`

Verify DLQ monitor subscriptions:
- `retriever-legal-dlq-sub`
- `retriever-clinical-dlq-sub`
- `retriever-commercial-dlq-sub`
- `retriever-social-dlq-sub`
- `retriever-knowledge-dlq-sub`
- `retriever-news-dlq-sub`

## 5. Container Image Build and Push

Use repository `Dockerfile` multi-stage targets.

Examples:

```bash
docker build --target planner -t <acr>/planner:<tag> .
docker build --target supervisor -t <acr>/supervisor:<tag> .
docker build --target executor -t <acr>/executor:<tag> .
docker build --target retriever-worker -t <acr>/retriever-worker:<tag> .
```

Push images:

```bash
docker push <acr>/planner:<tag>
docker push <acr>/supervisor:<tag>
docker push <acr>/executor:<tag>
docker push <acr>/retriever-worker:<tag>
```

## 6. Runtime Configuration Requirements

At deploy time, ensure all required env vars are present.

Critical:
- OpenAI endpoint/key/deployment
- Cosmos endpoint/key/database/container names
- Service Bus connection string
- Key Vault URL (if resolving secrets at startup)

Recommended:
- Redis URL
- Postgres URL
- AI Search endpoint/key
- telemetry settings

Retriever-specific:
- Set `SERVICE_BUS_SUBSCRIPTION` explicitly per retriever container.

## 7. Service Startup Targets

Expected service ports:
- Planner: `8000`
- Supervisor: `8001`
- Executor: `8002`
- Retrievers: `8080`
- MCP: `8010`

Health endpoints:
- `/health` on each service

## 8. Post-Deployment Verification

1. Health checks for all services.
2. Create a session through Planner.
3. Observe status transitions in Planner session endpoint.
4. Confirm retriever processing and result persistence.
5. Validate session and execute report generation.
6. Confirm report URL/payload availability.

## 9. Rollback Strategy

Container Apps revisions:
1. List revisions for service.
2. Activate previous healthy revision.
3. Verify health and core workflow.

General fallback order:
1. Roll back application image.
2. Roll back config changes.
3. Roll back infrastructure only if breaking schema/resource change was introduced.

## 10. Security and Secret Management

Preferred production pattern:
- Store secrets in Key Vault.
- Resolve into env at startup through bootstrap flow.
- Avoid baking credentials into images or static files.

## 11. Deployment Risks and Guardrails

High-risk changes:
- Topic/subscription name changes
- Session schema contract changes
- API path contract changes used by frontend/MCP

Guardrails:
- Keep docs and code in lockstep.
- Verify planner API contract and websocket path after deploy.
- Run smoke test workflow before any demo or release.
