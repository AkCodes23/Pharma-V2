# Pharma Agentic AI — Operational Runbook

## 1. Deployment

### Prerequisites

- Azure CLI authenticated (`az login`)
- AKS credentials configured (`az aks get-credentials`)
- Docker images built and pushed to ACR

### Deploy Infrastructure

```bash
# Deploy all Azure resources
az deployment group create \
  --resource-group pharma-ai-prod-rg \
  --template-file infra/bicep/main.bicep \
  --parameters environment=prod

# Apply K8s manifests
kubectl apply -f infra/k8s/deployment.yaml
kubectl apply -f infra/k8s/keda-scalers.yaml
```

### Run Database Migrations

```bash
alembic upgrade head
```

## 2. Health Checks

| Service | Endpoint | Expected |
| ------- | -------- | -------- |
| Planner | `GET /health` on port 8000 | `{"status": "healthy"}` |
| Supervisor | `GET /health` on port 8001 | `{"status": "healthy"}` |
| Executor | `GET /health` on port 8002 | `{"status": "healthy"}` |

### Check All Pods

```bash
kubectl get pods -n pharma-ai
kubectl top pods -n pharma-ai
```

## 3. Common Issues

### Service Bus Queue Backlog

**Symptom**: Tasks accumulating in queues, KEDA not scaling.

**Resolution**:

1. Check KEDA scaler status: `kubectl get scaledobject -n pharma-ai`
2. Verify Service Bus connection: `kubectl logs deployment/retriever-workers -n pharma-ai`
3. Manual scale: `kubectl scale deployment/retriever-workers --replicas=5 -n pharma-ai`

### Cosmos DB Throttling (429)

**Symptom**: HTTP 429 errors in logs.

**Resolution**:

1. Check RU consumption in Azure Portal
2. Increase autoscale max throughput in Bicep parameters
3. Redeploy: `az deployment group create ...`

### Graph Client Gremlin Errors

**Symptom**: Entity ingestion failing in production.

**Resolution**:

1. Check `GREMLIN_USE_GREMLIN` flag is set correctly
2. Verify Cosmos Gremlin endpoint: `GREMLIN_ENDPOINT`
3. Fallback: Set `GREMLIN_USE_GREMLIN=false` to use Neo4j

### NER Service Degraded

**Symptom**: All entities extracted via regex (lower quality).

**Resolution**:

1. Check `AI_LANGUAGE_ENDPOINT` and `AI_LANGUAGE_API_KEY` are set
2. Verify Azure AI Language quota in Azure Portal
3. Regex fallback is automatic — no downtime

### WebSocket/PubSub Not Delivering

**Symptom**: Frontend not receiving real-time updates.

**Resolution**:

1. Check `WEB_PUBSUB_USE_AZURE` flag
2. Verify PubSub connection string
3. For local dev: ensure Redis is running for Pub/Sub fan-out

## 4. Rollback

```bash
# Rollback to previous deployment
kubectl rollout undo deployment/planner-agent -n pharma-ai
kubectl rollout undo deployment/supervisor-agent -n pharma-ai
kubectl rollout undo deployment/executor-agent -n pharma-ai
kubectl rollout undo deployment/frontend -n pharma-ai

# Verify rollback
kubectl rollout status deployment/planner-agent -n pharma-ai
```

## 5. Secrets Rotation

1. Update secrets in Azure Key Vault
2. Recreate K8s secret: `kubectl create secret generic pharma-ai-secrets --from-env-file=.env -n pharma-ai --dry-run=client -o yaml | kubectl apply -f -`
3. Restart deployments: `kubectl rollout restart deployment -n pharma-ai`

## 6. DPO Training Pipeline

```bash
# Export training data
python -m src.ml.dpo_training --data models/dpo/training_data.jsonl --output models/dpo --backend local

# Submit to Azure fine-tuning (production)
python -m src.ml.dpo_training --data models/dpo/training_data.jsonl --output models/dpo --backend azure
```
