# Agent Registry

Last updated: 2026-03-02

This document is the operational source of truth for all runtime agents/services in this repository, including responsibilities, input/output contracts, bus bindings, and failure behavior.

## 1. Runtime Topology

Core flow:
1. Planner receives a user query and creates a session.
2. Planner publishes one task per selected pillar.
3. Retriever agents consume pillar tasks, execute deterministic tools, and persist findings.
4. Supervisor validates grounding/conflicts.
5. Executor produces final artifacts and marks session complete.

Supporting services:
- Quality Evaluator: quality scoring for intermediate outputs
- Prompt Enhancer: rewrites low-quality tasks/prompts for retry
- MCP server: external control-plane and tool gateway

## 2. Planner Agent

- Type: `PLANNER`
- Service: FastAPI
- Entry: `src/agents/planner/main.py`
- Port: `8000`

### Responsibility
- Accept user query sessions.
- Decompose intent to structured task graph.
- Publish task messages to bus.
- Serve session status and report metadata endpoints.
- Provide websocket stream endpoint for session updates.

### Endpoints
- `POST /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}/report`
- `GET /audit`
- `GET /metrics/agents`
- `GET /health`
- `WS /ws/sessions/{session_id}`

### Lifecycle dependencies
- CosmosDB client
- Redis client
- ServiceBusPublisher
- Audit service
- Websocket manager background tasks

### Failure behavior
- Returns `503` when dependencies are not initialized.
- Returns `400` for decomposition/business validation errors.
- Returns `500` for internal publish/persistence failures.

## 3. Retriever Agents

All retrievers share a common runtime pattern:
- Service: FastAPI with background worker thread
- Common health endpoint: `GET /health`
- Base class: `src/agents/retrievers/base_retriever.py`
- Runtime wrapper: `src/agents/retrievers/runtime.py`

### Common execution lifecycle
1. Consume Service Bus message.
2. Set task status `RUNNING`.
3. Execute toolchain with timeout protection.
4. Persist result and citations.
5. Set task status `COMPLETED`, `RETRYING`, `FAILED`, or `DLQ`.
6. Emit audit events.

### Shared resilience/performance controls
- Circuit breaker per retriever.
- Timeout-controlled tool execution.
- Service Bus prefetch and batch receive.
- Optional RAG augmentation in base retriever.

### 3.1 Legal Retriever
- Type: `LEGAL_RETRIEVER`
- Entry: `src/agents/retrievers/legal/main.py`
- Default subscription: `retriever-legal-sub`
- Topic: `legal-tasks`

Tools:
- Orange Book lookup
- Patent exclusivity search
- IPO patent search

### 3.2 Clinical Retriever
- Type: `CLINICAL_RETRIEVER`
- Entry: `src/agents/retrievers/clinical/main.py`
- Default subscription: `retriever-clinical-sub`
- Topic: `clinical-tasks`

Tools:
- ClinicalTrials search
- Phase filtering
- CDSCO lookup

### 3.3 Commercial Retriever
- Type: `COMMERCIAL_RETRIEVER`
- Entry: `src/agents/retrievers/commercial/main.py`
- Default subscription: `retriever-commercial-sub`
- Topic: `commercial-tasks`

Tools:
- Market data estimation
- Revenue retrieval
- Attractiveness scoring

### 3.4 Social Retriever
- Type: `SOCIAL_RETRIEVER`
- Entry: `src/agents/retrievers/social/main.py`
- Default subscription: `retriever-social-sub`
- Topic: `social-tasks`

Tools:
- FAERS query
- Safety score calculation

### 3.5 Knowledge Retriever
- Type: `KNOWLEDGE_RETRIEVER`
- Entry: `src/agents/retrievers/knowledge/main.py`
- Default subscription: `retriever-knowledge-sub`
- Topic: `knowledge-tasks`

Tools:
- Hybrid internal search via RAG pipeline

### 3.6 News Retriever
- Type: `NEWS_RETRIEVER`
- Entry: `src/agents/retrievers/news/main.py`
- Default subscription: `retriever-news-sub`
- Topic: `news-tasks`

Tools:
- Tavily-backed concurrent news/release/deal search

## 4. Supervisor Agent

- Type: `SUPERVISOR`
- Service: FastAPI
- Entry: `src/agents/supervisor/main.py`
- Port: `8001`

### Responsibility
- Validate completed session result set.
- Detect grounding/consistency issues.
- Persist validation outcome.

### Endpoints
- `POST /api/v1/sessions/{session_id}/validate`
- `GET /health`

### Validation gate
- Session task graph must be terminal (`COMPLETED` or `DLQ`) before validation.

## 5. Executor Agent

- Type: `EXECUTOR`
- Service: FastAPI
- Entry: `src/agents/executor/main.py`
- Port: `8002`

### Responsibility
- Synthesize final report from validated results.
- Generate optional charts and PDF artifact.
- Complete session decision/rationale/report URL.

### Endpoints
- `POST /api/v1/sessions/{session_id}/execute`
- `GET /health`

## 6. Quality Evaluator Agent

- Type: `QUALITY_EVALUATOR`
- Service: FastAPI
- Entry: `src/agents/quality_evaluator/main.py`
- Port: `8080`

### Endpoints
- `POST /evaluate`
- `GET /health`

### Role
- Score factual accuracy, citation completeness, and relevance.
- Return pass/fail with thresholded overall score.
- Fail-open on evaluator errors.

## 7. Prompt Enhancer Agent

- Type: `PROMPT_ENHANCER`
- Service: FastAPI
- Entry: `src/agents/prompt_enhancer/main.py`
- Port: `8080`

### Endpoints
- `POST /enhance`
- `GET /health`

### Role
- Rewrite low-quality retriever prompt/task text.
- Preserve fallback path to original prompt on failure.

## 8. MCP Server

- Service: FastMCP
- Entry: `src/mcp/mcp_server.py`
- Port: `8010` (HTTP transport mode)

### Role
- Expose platform tools/resources to MCP clients.
- Proxy planner workflows and selected external search operations.

### High-level tools
- Session create/get/list
- Report retrieval
- FDA and ClinicalTrials lookup
- Agent status and capabilities query

## 9. Bus and Subscription Matrix

### Service Bus topics
- `legal-tasks`
- `clinical-tasks`
- `commercial-tasks`
- `social-tasks`
- `knowledge-tasks`
- `news-tasks`

### Primary retriever subscriptions
- `retriever-legal-sub`
- `retriever-clinical-sub`
- `retriever-commercial-sub`
- `retriever-social-sub`
- `retriever-knowledge-sub`
- `retriever-news-sub`

### DLQ monitor subscriptions
- `retriever-legal-dlq-sub`
- `retriever-clinical-dlq-sub`
- `retriever-commercial-dlq-sub`
- `retriever-social-dlq-sub`
- `retriever-knowledge-dlq-sub`
- `retriever-news-dlq-sub`

## 10. State Model Summary

Session status progression:
- `PLANNING` -> `RETRIEVING` -> `VALIDATING` -> `SYNTHESIZING` -> `COMPLETED`
- Failure path to `FAILED` is possible based on orchestration/outcome.

Task status progression:
- `QUEUED` -> `RUNNING` -> `COMPLETED`
- Retry/failure path: `RETRYING`, `FAILED`, `DLQ`

## 11. Observability and Audit

- Audit entries are written for key actions across planner/retrievers/supervisor/executor.
- Planner exposes `/audit` for operational inspection.
- Metrics endpoint `/metrics/agents` provides derived latency/success aggregates.
- Websocket manager supports local Redis-backed fan-out and Azure Web PubSub mode.

## 12. Operational Assumptions

- For demo stability, each retriever container should set explicit `SERVICE_BUS_SUBSCRIPTION`.
- Topic naming convention is `*-tasks`; legacy `pharma.tasks.*` aliases are only for compatibility layers.
- Worker services are intended to be long-running services with health probes, not one-shot jobs.
