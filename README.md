# Pharma Agentic AI

Distributed multi-agent platform for pharmaceutical market intelligence. The system decomposes a user query into pillar-specific tasks, executes deterministic retrieval tools, validates grounding, and produces a final decision report.

This repository currently supports:
- Planner API service (`:8000`)
- Supervisor service (`:8001`)
- Executor service (`:8002`)
- Six retriever worker-services (Legal, Clinical, Commercial, Social, Knowledge, News)
- MCP gateway (`:8010`)
- Quality Evaluator and Prompt Enhancer services
- Local stack via Docker Compose (Kafka + Redis + Postgres + observability)
- Azure infrastructure via Bicep

## 1. System Overview

Request lifecycle:
1. User submits query to Planner.
2. Planner decomposes intent into tasks and persists session state in Cosmos.
3. Planner publishes one message per pillar to message bus.
4. Retriever services consume pillar messages from Service Bus subscriptions.
5. Each retriever executes deterministic tools and writes results to Cosmos.
6. Supervisor validates grounding and conflict state.
7. Executor synthesizes report, generates artifacts, completes session.
8. Frontend or MCP clients poll/stream session status and fetch report output.

Current routing conventions:
- Service Bus topics: `legal-tasks`, `clinical-tasks`, `commercial-tasks`, `social-tasks`, `knowledge-tasks`, `news-tasks`
- Retriever subscriptions:
  - `retriever-legal-sub`
  - `retriever-clinical-sub`
  - `retriever-commercial-sub`
  - `retriever-social-sub`
  - `retriever-knowledge-sub`
  - `retriever-news-sub`

Broker mode contract:
- **Service Bus mode (default):** Planner/retreivers use Azure Service Bus `*-tasks` topics.
- **Kafka/Event Hubs mode (analytics/eventing):** Kafka topics use `pharma.tasks.*` and `pharma.events.*`.
- Avoid mixed runtime assumptions in a single deployment. If `KAFKA_USE_EVENT_HUBS=true`, configure
  `KAFKA_EVENT_HUBS_CONNECTION_STRING`; retriever task consumption still relies on Service Bus unless
  explicitly migrated.

## 2. Repository Structure

- `src/agents/planner/`: Planner FastAPI app and decomposition/publishing flow
- `src/agents/retrievers/`: Base retriever + pillar implementations
- `src/agents/supervisor/`: Validation and conflict checks
- `src/agents/executor/`: Report generation and artifact orchestration
- `src/agents/quality_evaluator/`: A2A quality scoring service
- `src/agents/prompt_enhancer/`: A2A prompt rewrite service
- `src/shared/`: shared config, infra clients, telemetry, websocket, models
- `src/mcp/`: MCP server exposing platform tools/resources
- `src/frontend/`: Next.js dashboard
- `infra/bicep/main.bicep`: consolidated Azure provisioning
- `docker-compose.yml`: complete local runtime stack
- `docs/`: onboarding, API, deployment, runbook, ADRs

## 3. Service Contracts

### Planner (`src.agents.planner.main:app`)
Port: `8000`

Endpoints:
- `POST /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}/report`
- `GET /audit`
- `GET /metrics/agents`
- `GET /health`
- `WS /ws/sessions/{session_id}`

### Supervisor (`src.agents.supervisor.main:app`)
Port: `8001`

Endpoints:
- `POST /api/v1/sessions/{session_id}/validate`
- `GET /health`

### Executor (`src.agents.executor.main:app`)
Port: `8002`

Endpoints:
- `POST /api/v1/sessions/{session_id}/execute`
- `GET /health`

### Retriever services (`src.agents.retrievers.<pillar>.main`)
Port: `8080` per retriever container

Endpoints:
- `GET /health`

Background behavior:
- Starts Service Bus consumer loop on app lifespan startup.
- Consumes using configured `SERVICE_BUS_SUBSCRIPTION`.
- Writes task status/result back to Cosmos.

### MCP (`src/mcp/mcp_server.py http`)
Port: `8010`

Provides tools:
- create session
- get/list sessions
- get report
- FDA and ClinicalTrials search
- capabilities and agent status

### Quality Evaluator / Prompt Enhancer
Port: `8080`

Endpoints:
- Quality Evaluator: `POST /evaluate`, `GET /health`
- Prompt Enhancer: `POST /enhance`, `GET /health`

## 4. Prerequisites

Required:
- Python 3.11+ (3.12 recommended)
- Docker Desktop (for full local stack)
- Node.js 20+ (frontend local dev)

For Azure deployment:
- Azure CLI
- Contributor access to target subscription/resource group

## 5. Environment Configuration

Start from `.env.example`:

```bash
cp .env.example .env
```

Minimum variables to run core services locally:
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `COSMOS_DB_ENDPOINT`
- `COSMOS_DB_KEY`
- `SERVICE_BUS_CONNECTION_STRING` (if running with Service Bus)

Common local defaults in Compose:
- Redis: `redis://...@redis:6379/...`
- Postgres: `postgresql://pharma:...@postgres:5432/pharma_ai`
- Kafka: `kafka:29092`

## 6. Running the Project

### Option A: Full stack via Docker Compose (recommended for demo)

```bash
docker compose up -d --build
docker compose ps
```

Important URLs:
- Frontend: `http://localhost:3000`
- Planner API: `http://localhost:8000`
- Supervisor: `http://localhost:8001`
- Executor: `http://localhost:8002`
- MCP HTTP transport: `http://localhost:8010`
- Kafka UI: `http://localhost:8080`
- Jaeger: `http://localhost:16686`

Stop:

```bash
docker compose down -v
```

### Option B: Service-by-service local run

Backend service examples:

```bash
uvicorn src.agents.planner.main:app --host 0.0.0.0 --port 8000
uvicorn src.agents.supervisor.main:app --host 0.0.0.0 --port 8001
uvicorn src.agents.executor.main:app --host 0.0.0.0 --port 8002
python -m src.agents.retrievers.legal.main
```

Frontend:

```bash
cd src/frontend
npm install
npm run dev
```

## 7. Testing and Quality

Run tests:

```bash
pytest tests/ -v
```

Run lint/type checks:

```bash
ruff check src tests
ruff format src tests
mypy src --ignore-missing-imports
```

Notes:
- Some unit tests require optional dependencies (`respx`, Azure SDKs) and env vars.
- Collection can fail without required packages or OpenAI config.

## 8. Demo Execution Checklist

Before demo:
1. `docker compose ps` shows all primary services healthy.
2. `GET /health` succeeds for planner/supervisor/executor.
3. Retriever services have `SERVICE_BUS_SUBSCRIPTION` env values matching Bicep subscriptions.
4. Create a session with Planner and verify status progresses through:
   - `PLANNING`
   - `RETRIEVING`
   - `VALIDATING`
   - `SYNTHESIZING`
   - `COMPLETED`
5. Report endpoint returns payload for `format=pdf` or `format=summary`.

## 9. Documentation Index

- [Agent Registry](agents.md)
- [Developer Onboarding](docs/developer-onboarding.md)
- [API Integration Guide](docs/api-integration-guide.md)
- [Deployment Guide](docs/deployment-guide.md)
- [Operational Runbook](docs/runbook.md)
- [Architecture Decision Records](docs/adr.md)

## 10. Known Constraints

- Full integration depends on external APIs and Azure credentials.
- Some local tests are environment-sensitive.
- WebSocket fan-out is Redis-backed in local mode and Web PubSub-backed when configured for Azure.

## 11. License

Proprietary. Internal use only unless explicitly authorized.
