# Developer Onboarding

This guide is for engineers working on the repository codebase.

## 1. Scope and Expectations

You should be able to:
- Boot the full local stack.
- Run and inspect planner/retriever/supervisor/executor flows.
- Execute tests and linters.
- Safely update infra/app contracts without breaking service startup.

## 2. Local Prerequisites

Required:
- Python 3.11+ (3.12 preferred)
- Docker Desktop
- Node.js 20+
- Git

Recommended:
- `ruff`, `mypy`, `pytest` available in your active Python environment

## 3. Initial Setup

```bash
git clone <repo-url>
cd "Pharma V2"
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
```

Frontend setup:

```bash
cd src/frontend
npm install
cd ../..
```

Create env file:

```bash
copy .env.example .env
```

Populate required secrets/config for your target run mode.

## 4. Fast Start Commands

Using Makefile:

```bash
make dev
make status
make logs
```

Direct compose:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f planner
```

## 5. Service Map (Local Compose)

Application:
- Planner: `http://localhost:8000`
- Supervisor: `http://localhost:8001`
- Executor: `http://localhost:8002`
- MCP: `http://localhost:8010`
- Frontend: `http://localhost:3000`

Infrastructure/ops:
- Kafka UI: `http://localhost:8080`
- Jaeger: `http://localhost:16686`
- Redis: `localhost:6379`
- Postgres: `localhost:5432`

## 6. First Smoke Test

1. Verify planner health:

```bash
curl http://localhost:8000/health
```

2. Create session:

```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"query":"Analyze generic entry strategy for semaglutide in US","user_id":"dev-user"}'
```

3. Poll status:

```bash
curl http://localhost:8000/api/v1/sessions/<session_id>
```

4. Optional websocket stream:
- connect to `ws://localhost:8000/ws/sessions/<session_id>`

## 7. Development Workflow

1. Create feature branch.
2. Make code changes.
3. Run formatting/lint/type/tests.
4. Validate service startup for touched components.
5. Update docs for any contract/infrastructure changes.

## 8. Quality Gates

Run locally before PR:

```bash
ruff check src tests
ruff format src tests
mypy src --ignore-missing-imports
pytest tests/ -v
```

Notes:
- Some test modules require optional deps (`respx`, Azure SDK packages).
- Some service modules require OpenAI env vars at import/runtime.

## 9. Core Architectural Conventions

- Planner is the API entrypoint and session state owner.
- Retrievers are worker-services with health endpoints and background consumers.
- Message topic naming source of truth is Service Bus `*-tasks` topics.
- Subscription names in retriever runtime must match Bicep resources.
- Fail-open behavior is used in selected quality/aux flows to keep pipeline moving.

## 10. Critical Files to Know

- `src/agents/planner/main.py`
- `src/agents/retrievers/base_retriever.py`
- `src/agents/retrievers/runtime.py`
- `src/shared/infra/servicebus_client.py`
- `src/shared/infra/cosmos_client.py`
- `src/shared/infra/websocket.py`
- `infra/bicep/main.bicep`
- `docker-compose.yml`

## 11. Common Pitfalls

- Service starts but healthcheck fails: `PORT` env mismatch.
- Retriever consumes nothing: wrong `SERVICE_BUS_SUBSCRIPTION`.
- Planner API 404 from MCP/frontend: endpoint path drift.
- High Cosmos load: bypassing cache for repeated session polling.
- Busy CPU in websocket worker: tight redis poll loops.

## 12. Troubleshooting Quick Commands

```bash
docker compose ps
docker compose logs -f planner
docker compose logs -f retriever-legal
python -m py_compile src/agents/planner/main.py
pytest -q --maxfail=1
```

## 13. Documentation Discipline

When changing behavior, update at minimum:
- `README.md`
- `agents.md`
- one or more files in `docs/` for API/deployment/runbook impact
- relevant ADR when a long-term architecture decision changes
