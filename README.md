# Pharma Agentic AI (Standalone Demo Branch)

This branch (`feature/standalone-demo`) is a demo-only runtime that preserves core workflows without Azure dependencies.

## What Changed
- Data store: Azure Cosmos DB -> PostgreSQL
- Task bus: Azure Service Bus -> Kafka
- Object storage: Azure Blob -> MinIO
- Decomposition/report synthesis: Azure OpenAI -> deterministic fixtures
- Auth: header/Entra assumptions -> anonymous demo auth (`X-Demo-User` optional)
- Orchestration: planner auto-calls supervisor/executor when retrieval tasks are terminal

Production assets (`infra/bicep`, Azure workflows, Azure adapters) remain in-repo and are not removed.

## Quick Start
1. Copy demo env:
   - `cp .env.demo .env`
2. Start the full stack:
   - `docker compose up --build`
3. Open UI:
   - [http://localhost:3000](http://localhost:3000)

Core APIs:
- Planner: [http://localhost:8000](http://localhost:8000)
- Supervisor: [http://localhost:8001](http://localhost:8001)
- Executor: [http://localhost:8002](http://localhost:8002)
- MinIO Console: [http://localhost:9001](http://localhost:9001)

## Demo Flow (curl)
Create session:

```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Content-Type: application/json" \
  -H "X-Demo-User: demo-user" \
  -d '{"query":"Assess 2027 generic launch for Keytruda in India"}'
```

Poll status:

```bash
curl -H "X-Demo-User: demo-user" \
  http://localhost:8000/api/v1/sessions/<session_id>
```

Expected progression:
- `PLANNING -> RETRIEVING -> VALIDATING -> SYNTHESIZING -> COMPLETED`

Get report metadata:

```bash
curl -H "X-Demo-User: demo-user" \
  "http://localhost:8000/api/v1/sessions/<session_id>/report?format=pdf"
```

## Verification
- Run tests:
  - `pytest -v`
- Run smoke script:
  - `./scripts/smoke_standalone_demo.ps1`

## Demo Docs
- [Dependency Map](docs/standalone-demo/dependency-map.md)
- [Azure Removal Matrix](docs/standalone-demo/azure-removal-matrix.md)
- [Runbook](docs/standalone-demo/runbook.md)
