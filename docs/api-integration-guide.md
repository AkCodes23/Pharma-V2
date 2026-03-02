# Pharma Agentic AI — API Integration Guide

## Base URL

| Environment | URL |
|-------------|-----|
| Local | `http://localhost:8000` |
| Staging | `https://pharmaai-staging-planner.<region>.azurecontainerapps.io` |
| Production | `https://pharmaai-prod-planner.<region>.azurecontainerapps.io` |

## Authentication

All API requests require a Bearer token from Azure Entra ID:

```bash
TOKEN=$(az account get-access-token --resource api://pharmaai --query accessToken -o tsv)
curl -H "Authorization: Bearer $TOKEN" https://<base-url>/api/v1/sessions
```

## Endpoints

### POST /api/v1/sessions — Create Session

Creates a new drug analysis session and triggers the multi-agent pipeline.

**Request:**
```json
{
  "query": "Analyze biosimilar entry strategy for Humira in EU market by 2027",
  "user_id": "user-azure-oid"
}
```

**Response (201):**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PLANNING",
  "task_count": 5,
  "tasks": [
    { "task_id": "t-001", "pillar": "LEGAL", "description": "Patent analysis", "status": "QUEUED" },
    { "task_id": "t-002", "pillar": "CLINICAL", "description": "Trial pipeline", "status": "QUEUED" }
  ],
  "websocket_url": "/ws/sessions/550e8400-e29b-41d4-a716-446655440000"
}
```

### GET /api/v1/sessions/{session_id} — Get Session Status

**Response (200):**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "COMPLETED",
  "query": "Analyze biosimilar entry strategy for Humira...",
  "task_graph": [...],
  "agent_results": [...],
  "validation": {
    "is_valid": true,
    "grounding_score": 0.87,
    "conflicts": []
  },
  "decision": "CONDITIONAL",
  "decision_rationale": "Strong pipeline but patent expiry timing uncertain",
  "report_url": "https://pharmaai.blob.core.windows.net/reports/550e8400.pdf",
  "created_at": "2026-03-02T14:30:00Z",
  "updated_at": "2026-03-02T14:32:15Z"
}
```

### GET /health — Health Check

**Response (200):**
```json
{ "status": "healthy", "service": "planner-agent" }
```

### WebSocket /ws/sessions/{session_id} — Real-Time Updates

Connect to receive live session progress updates:

```javascript
const ws = new WebSocket('wss://<base-url>/ws/sessions/<session_id>');
ws.onmessage = (event) => {
  const update = JSON.parse(event.data);
  // update.type: 'TASK_STARTED' | 'TASK_COMPLETED' | 'VALIDATION_RESULT' | 'SESSION_COMPLETED'
  console.log(`${update.type}: ${update.pillar} — ${update.status}`);
};
```

## Session Status Flow

```
PLANNING → RETRIEVING → VALIDATING → SYNTHESIZING → COMPLETED
                                                   ↘ FAILED
```

## Error Codes

| Status | Meaning |
|--------|---------|
| 400 | Invalid request (query too short, invalid drug name) |
| 401 | Missing or invalid Bearer token |
| 404 | Session not found |
| 429 | Rate limit exceeded (per user_id) |
| 500 | Internal error (logged with correlation ID) |
| 503 | Service not ready (still initializing) |

## Rate Limits

- **10 sessions/minute** per `user_id`
- **100 requests/minute** per IP for status queries

## MCP Integration

The platform exposes an MCP server for LLM tool-use integration:

```python
# MCP tool: pharma_create_session
params = {
    "drug_name": "Keytruda",
    "target_market": "US",
    "user_id": "mcp-client"
}
```

See `src/mcp/mcp_server.py` for all 8 available MCP tools.
