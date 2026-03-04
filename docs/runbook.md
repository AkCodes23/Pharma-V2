# Operational Runbook

This runbook is for operators supporting local demo, staging, or production-like environments.

## 1. Core Operational Goals

- Keep all services healthy and responsive.
- Ensure end-to-end session processing completes.
- Detect and resolve queue, persistence, or contract drift quickly.

## 2. Daily Health Checklist

1. Verify service health endpoints:
   - Planner `:8000/health`
   - Supervisor `:8001/health`
   - Executor `:8002/health`
   - Retriever services `:8080/health` (per container)
2. Verify message bus connectivity.
3. Verify Cosmos read/write path.
4. Verify report endpoint for a known-good session.

## 3. Local Compose Operations

Start stack:

```bash
docker compose up -d --build
```

Check status:

```bash
docker compose ps
```

Tail logs:

```bash
docker compose logs -f planner
docker compose logs -f retriever-legal
```

Stop and clean:

```bash
docker compose down -v
```

## 4. Incident Response Playbooks

### 4.1 Service fails startup

Symptoms:
- container restarting
- healthcheck failing

Actions:
1. Inspect logs for import/config errors.
2. Confirm `PORT` environment variable matches expected service port.
3. Validate required env vars are set.
4. Rebuild image if code and container mismatch suspected.

### 4.2 Retriever not consuming tasks

Symptoms:
- session stuck in `RETRIEVING`
- queue depth increases

Actions:
1. Verify retriever service is healthy.
2. Confirm `SERVICE_BUS_SUBSCRIPTION` matches provisioned subscription.
3. Confirm topic and subscription exist.
4. Check Service Bus auth/connection string.

### 4.3 Session polling is slow or expensive

Symptoms:
- high Cosmos RU usage
- frequent status polling overhead

Actions:
1. Confirm cache layer is active.
2. Increase poll interval on clients if needed.
3. Inspect session endpoint latency.

### 4.4 WebSocket updates missing

Symptoms:
- polling works, stream updates do not

Actions:
1. Verify planner websocket endpoint path: `/ws/sessions/{session_id}`.
2. In local mode, verify Redis is running and subscriber loop started.
3. In Azure mode, verify Web PubSub config values and token flow.

### 4.5 Audit backlog or gaps

Symptoms:
- delayed or missing audit entries

Actions:
1. Check audit worker logs.
2. Verify Cosmos audit container access.
3. Confirm flush worker is running and service is not terminated abruptly.

## 5. Recovery Procedures

### 5.1 Restart a single service

```bash
docker compose restart planner
```

### 5.2 Restart all app services

```bash
docker compose restart planner supervisor executor retriever-legal retriever-clinical retriever-commercial retriever-social retriever-knowledge retriever-news
```

### 5.3 Recreate full environment

```bash
docker compose down -v
docker compose up -d --build
```

## 6. Performance Tuning Knobs

- Service Bus consumer `prefetch_count` and `max_messages`
- Retriever timeout settings in base retriever
- Frontend polling interval
- Cosmos RU autoscale thresholds
- Worker concurrency (Celery and retriever replicas)

## 7. Monitoring Targets

Track at minimum:
- session throughput and completion rate
- mean and p95 session completion time
- retriever error/retry/DLQ rates
- Cosmos and Service Bus latency/error rates
- healthcheck failure counts

## 8. Demo-Day Runbook

1. Bring stack up with compose.
2. Verify health endpoints.
3. Run one known demo query and confirm complete path.
4. Keep live logs open for planner + one retriever + executor.
5. If issue occurs, fall back to polling + summary report endpoint.

## 9. Escalation Guidance

Escalate when:
- multiple services fail concurrently
- persistent message loss or duplicate processing observed
- Cosmos writes failing across planner/retrievers
- core API contracts return repeated 404/500 errors after rollback

## 10. Post-Incident Checklist

- document root cause
- identify contract/config drift
- add/update regression tests
- update docs in `README.md`, `agents.md`, and `docs/*`
