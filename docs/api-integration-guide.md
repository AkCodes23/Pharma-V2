# API Integration Guide

This guide documents the externally relevant API contracts for integrating with the platform.

## 1. Base URLs

Local:
- Planner API: `http://localhost:8000`
- Supervisor API: `http://localhost:8001`
- Executor API: `http://localhost:8002`
- MCP HTTP transport: `http://localhost:8010`

In deployed environments, replace hostnames with your ingress/FQDN values.

## 2. Planner API

### 2.1 Create Session

`POST /api/v1/sessions`

Request body:

```json
{
  "query": "Analyze market-entry strategy for semaglutide in US",
  "user_id": "integration-user"
}
```

Response `201`:

```json
{
  "session_id": "uuid",
  "status": "PLANNING",
  "task_count": 6,
  "tasks": [
    {
      "task_id": "...",
      "pillar": "LEGAL",
      "description": "...",
      "status": "QUEUED"
    }
  ],
  "websocket_url": "/ws/sessions/uuid"
}
```

### 2.2 Get Session

`GET /api/v1/sessions/{session_id}`

Response includes:
- session identity and status
- original query
- task graph
- collected agent results
- validation block
- decision fields
- report URL and timestamps

### 2.3 List Sessions

`GET /api/v1/sessions`

Query params:
- `drug_name` (optional)
- `user_id` (optional)
- `status` (optional)
- `limit` (default 10, max 100)
- `offset` (default 0)

### 2.4 Get Session Report Metadata/Payload

`GET /api/v1/sessions/{session_id}/report`

Query param:
- `format`: `pdf` | `summary` | `json`

Behavior:
- `pdf`: returns report URL metadata
- `summary`: returns decision summary data
- `json`: returns expanded report/session payload

### 2.5 Audit Listing

`GET /audit`

Query params:
- `limit` (default 100, max 500)
- `session_id` (optional)

### 2.6 Agent Metrics

`GET /metrics/agents`

Returns derived metrics from recent sessions:
- average latency
- success rate
- invocation count

### 2.7 Health

`GET /health`

### 2.8 Session WebSocket Stream

`WS /ws/sessions/{session_id}`

Local mode:
- streams session events over planner websocket handler

Azure Web PubSub mode:
- planner returns redirect token payload via websocket negotiation path in manager behavior

## 3. Supervisor API

### 3.1 Validate Session

`POST /api/v1/sessions/{session_id}/validate`

Response shape:

```json
{
  "session_id": "uuid",
  "validated": true,
  "ready_for_execution": true,
  "is_valid": true,
  "grounding_score": 0.85,
  "conflict_count": 0
}
```

### 3.2 Health

`GET /health`

## 4. Executor API

### 4.1 Execute Session

`POST /api/v1/sessions/{session_id}/execute`

Response includes:
- final decision
- rationale
- report URL
- optional markdown/charts metadata

### 4.2 Health

`GET /health`

## 5. A2A Services

Quality Evaluator:
- `POST /evaluate`
- `GET /health`

Prompt Enhancer:
- `POST /enhance`
- `GET /health`

## 6. MCP Integration

MCP server (`src/mcp/mcp_server.py`) exposes tool wrappers for Planner and selected data sources.

Examples of tool-level capabilities:
- create session
- get/list sessions
- fetch report
- FDA search
- clinical trials search
- list capabilities
- get active agents

When integrating MCP clients, configure:
- `PLANNER_URL`
- `PHARMA_INTERNAL_API_KEY`

## 7. Status Model

Session status:
- `PLANNING`
- `RETRIEVING`
- `VALIDATING`
- `SYNTHESIZING`
- `COMPLETED`
- `FAILED`

Task status:
- `QUEUED`
- `RUNNING`
- `COMPLETED`
- `RETRYING`
- `FAILED`
- `DLQ`

## 8. Error Handling and Retries

Common HTTP codes:
- `400`: bad input/invalid request parameters
- `404`: session/resource not found
- `422`: validation errors (request schema)
- `429`: rate-limit behavior where configured
- `500`: internal processing failure
- `503`: service not initialized/ready

Integration recommendations:
- Retry `503` and transient `500` with exponential backoff.
- Do not retry `400/404/422` without request change.
- Poll session state for long-running operations.

## 9. Integration Patterns

Pattern A: Planner-only orchestration
1. Create session via Planner.
2. Poll Planner session endpoint.
3. Retrieve report endpoint when status is terminal.

Pattern B: Explicit orchestration (advanced)
1. Create session via Planner.
2. Trigger Supervisor validation endpoint.
3. Trigger Executor endpoint.
4. Poll Planner for final report URL.

## 10. Contract Stability Notes

- Planner session endpoints are the preferred stable integration surface.
- Internal retriever tool output fields can evolve with source APIs.
- Keep client logic resilient to additive fields in response payloads.
