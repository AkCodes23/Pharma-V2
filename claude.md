# Pharma Agentic AI - Claude Code Instructions

This file defines practical, code-aligned guidance for contributors and AI-assisted development workflows.

## 1. Purpose

Use this document when you are:
- adding or modifying service behavior
- changing message contracts or infrastructure mappings
- debugging startup/runtime issues
- preparing a demo or release

Primary goal: keep code, runtime contracts, and docs synchronized.

## 2. Current Runtime Architecture

Main execution chain:
1. Planner API receives query and creates session.
2. Planner decomposes query into tasks and publishes one task per pillar.
3. Retriever services consume pillar messages from Service Bus subscriptions.
4. Retrievers persist findings and citations to Cosmos session state.
5. Supervisor validates grounding and conflict state.
6. Executor synthesizes final report and completes session.

Supporting services:
- Quality Evaluator (`/evaluate`)
- Prompt Enhancer (`/enhance`)
- MCP server for tool-based integrations

## 3. Source of Truth Contracts

### 3.1 API Endpoints

Planner (`src/agents/planner/main.py`):
- `POST /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}/report`
- `GET /audit`
- `GET /metrics/agents`
- `GET /health`
- `WS /ws/sessions/{session_id}`

Supervisor (`src/agents/supervisor/main.py`):
- `POST /api/v1/sessions/{session_id}/validate`
- `GET /health`

Executor (`src/agents/executor/main.py`):
- `POST /api/v1/sessions/{session_id}/execute`
- `GET /health`

Retriever services (`src/agents/retrievers/*/main.py`):
- `GET /health`
- background consumer loop started by lifespan runtime wrapper

### 3.2 Topic and Subscription Naming

Service Bus topic naming convention (authoritative):
- `legal-tasks`
- `clinical-tasks`
- `commercial-tasks`
- `social-tasks`
- `knowledge-tasks`
- `news-tasks`

Retriever subscriptions:
- `retriever-legal-sub`
- `retriever-clinical-sub`
- `retriever-commercial-sub`
- `retriever-social-sub`
- `retriever-knowledge-sub`
- `retriever-news-sub`

DLQ monitor subscriptions:
- `retriever-legal-dlq-sub`
- `retriever-clinical-dlq-sub`
- `retriever-commercial-dlq-sub`
- `retriever-social-dlq-sub`
- `retriever-knowledge-dlq-sub`
- `retriever-news-dlq-sub`

Compatibility note:
- legacy `pharma.tasks.*` aliases may exist in compatibility code paths, but do not change source-of-truth naming without coordinated migration.

## 4. Service Startup and Container Rules

- Planner, Supervisor, Executor are FastAPI services.
- Retrievers are also FastAPI services and host a background worker thread.
- Health probes must target each service's actual port.
- Compose/runtime must set explicit `PORT` values where image healthcheck references it.
- Retrievers should set explicit `SERVICE_BUS_SUBSCRIPTION` env vars.

## 5. Configuration and Secrets

Typed settings live in `src/shared/config.py`.

High-impact config groups:
- `openai`
- `cosmos`
- `servicebus`
- `redis`
- `postgres`
- `kafka`
- `web_pubsub`
- `telemetry`

Secret strategy:
- local: `.env` / `.env.example`
- production: Key Vault + bootstrap resolution

Do not hardcode credentials in source or docs.

## 6. Data and State Ownership

- Cosmos session documents are source of truth for workflow state.
- Redis is cache and ephemeral coordination, not authoritative session storage.
- Postgres is used for analytics/background task data.

## 7. Reliability and Performance Patterns

- Base retriever includes timeout and circuit breaker behavior.
- Service Bus consumer uses prefetch and batched receive behavior.
- Planner session reads should use cache read-through strategy.
- Websocket manager runs background tasks for Redis fan-out and stale cleanup.
- Audit service runs background flush worker and supports batched persistence.

## 8. Development Workflow

1. Read impacted contracts before coding.
2. Implement minimal coherent change.
3. Update docs in same change set.
4. Compile/check touched modules.
5. Run tests available in environment.
6. Report residual risk and environment blockers explicitly.

## 9. Validation Commands

Compile selected modules:

```powershell
python -m py_compile src/agents/planner/main.py src/shared/infra/websocket.py
```

Run tests:

```powershell
pytest tests/ -v
```

Run static checks:

```powershell
ruff check src tests
mypy src --ignore-missing-imports
```

## 10. High-Risk Change Areas

Treat these as contract-critical:
- `src/shared/models/schemas.py`
- `src/shared/config.py`
- `src/shared/infra/servicebus_client.py`
- `src/shared/infra/message_broker.py`
- `src/agents/planner/main.py`
- `infra/bicep/main.bicep`
- `docker-compose.yml`

If modifying any of these, update docs immediately and verify runtime assumptions.

## 11. Demo-Readiness Checklist

Before demo:
1. All app services are healthy.
2. Session create endpoint works.
3. Retriever consumption is active for each pillar.
4. Session reaches `COMPLETED` on a known query.
5. Report endpoint returns expected payload.
6. UI and/or MCP can observe session progress.

## 12. Documentation Policy

Whenever behavior changes, update:
- `README.md`
- `agents.md`
- one or more files under `docs/`
- this file (`claude.md`) if contributor guidance changes
