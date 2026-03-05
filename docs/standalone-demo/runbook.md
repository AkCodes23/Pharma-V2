# Standalone Demo Runbook

## 1. Start
1. Copy config template:
   - `cp .env.demo .env`
2. Build and boot all services:
   - `docker compose up --build`

Expected core services:
- `planner` (`http://localhost:8000/health`)
- `supervisor` (`http://localhost:8001/health`)
- `executor` (`http://localhost:8002/health`)
- retrievers (`retriever-*`)
- `postgres`, `redis`, `kafka`, `minio`
- `frontend` (`http://localhost:3000`)

## 2. Submit Demo Session
Use anonymous demo auth header:

```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Content-Type: application/json" \
  -H "X-Demo-User: demo-user" \
  -d '{"query":"Assess 2027 generic launch for Keytruda in India"}'
```

Response includes `session_id` and task graph.

## 3. Poll Status Progression

```bash
curl -H "X-Demo-User: demo-user" \
  http://localhost:8000/api/v1/sessions/<session_id>
```

Expected status progression:
- `PLANNING`
- `RETRIEVING`
- `VALIDATING`
- `SYNTHESIZING`
- `COMPLETED`

Planner orchestrator auto-triggers supervisor/executor after task completion.

## 4. Fetch Report Metadata

```bash
curl -H "X-Demo-User: demo-user" \
  "http://localhost:8000/api/v1/sessions/<session_id>/report?format=pdf"
```

Report URL points to MinIO object path.

## 5. Validation Checks
- Submit same query twice and compare decision/rationale outputs for deterministic behavior.
- Submit unknown query and verify fallback fixture response remains structured and successful.
- Confirm no Azure endpoints are contacted by scanning logs for `azure.com` / `windows.net`.

## 6. Teardown
- Stop and remove all containers/volumes:
  - `docker compose down -v`
