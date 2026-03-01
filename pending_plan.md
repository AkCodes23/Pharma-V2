# Pharma Agentic AI — Pending Work (E2E Comprehensive Plan)

> **Last Updated**: 2026-03-01
> Full audit of every layer — what's built, what's pending, what needs testing, and what needs optimization.

---

## Executive Summary

### What's Built ✅

| Layer | Status | Files |
|-------|:------:|------:|
| **Planner Agent** (FastAPI :8000) | ✅ Fully implemented | 5 files |
| **Supervisor Agent** (Validator + Conflict Resolver) | ✅ Fully implemented | 4 files |
| **Executor Agent** (Report + PDF + Charts) | ✅ Fully implemented | 5 files |
| **6 Retriever Agents** (Legal, Clinical, Commercial, Social, Knowledge, News) | ✅ Real APIs (no mocks) | 22 files |
| **Quality Evaluator** (A2A sub-agent) | ✅ Implemented | 2 files |
| **Prompt Enhancer** (A2A sub-agent) | ✅ Implemented | 2 files |
| **Base Retriever Lifecycle** (Circuit breaker, timeout, DLQ) | ✅ Production-grade | 1 file (533 lines) |
| **A2A Agent Mesh** (HTTP/2, Kafka, circuit breaker) | ✅ Implemented | 8 files |
| **SPAR Reflection Engine** | ✅ Implemented | 2 files |
| **RAG Pipeline** (Chunker + Ingestion + Retriever) | ✅ Implemented | 4 files |
| **Shared Infrastructure** | ✅ 21 modules | 21 files |
| **Pydantic Models** (Schemas + Enums) | ✅ Complete | 3 files |
| **Config** (12 service configs) | ✅ Unified | 1 file (362 lines) |
| **Frontend** (Next.js 15 dashboard) | ✅ Live API wiring | 5+ files |
| **MCP Server** (8 tools, resource reads) | ✅ Functional | 1 file (708 lines) |
| **DPO Training** (Data collector + trainer) | ✅ Implemented (untested) | 2 files |
| **Docker Compose** (17 services) | ✅ Production-grade | 1 file (437 lines) |
| **CI/CD** (8-job GitHub Actions) | ✅ Implemented | 2 YAML files |
| **Bicep IaC** (12+ Azure resources) | ✅ Implemented | 1 file (277 lines) |
| **K8s Deployments** (base manifests) | ⚠️ Partial (3 of 15) | 6 files |
| **KEDA Scalers** | ⚠️ Partial (4 of 7) | 1 file |
| **Unit Tests** | ⚠️ Partial (15 of 23 needed) | 15 files |
| **Documentation** (ADR + Runbook) | ⚠️ Started | 2 files |

### What's Pending ❌

| Category | Pending Items | Blocking Production? |
|----------|:---:|:---:|
| **🔵 Azure E2E Readiness** | **18** | **✅ Yes (CRITICAL)** |
| Testing — Unit Tests (Agent Core) | 8 | ✅ Yes |
| Testing — Integration & E2E | 4 | ✅ Yes |
| Testing — Performance & Load | 3 | ⚠️ Partial |
| K8s Deployment Manifests | 12 | ✅ Yes |
| KEDA ScaledObjects | 3 | ⚠️ Partial |
| CI/CD Pipeline Completion | 5 | ⚠️ Partial |
| Bicep IaC Gaps | 4 | ⚠️ Partial |
| Database Migrations | 3 | ✅ Yes |
| Secrets Management | 3 | ✅ Yes |
| Security Hardening | 6 | ✅ Yes |
| API & Data Quality | 4 | ⚠️ Partial |
| ML Pipeline (DPO) | 5 | ❌ No |
| MCP Server Hardening | 4 | ❌ No |
| Observability Gaps | 5 | ⚠️ Partial |
| Documentation | 5 | ❌ No |
| Frontend Polish | 4 | ⚠️ Partial |
| Performance Optimization | 6 | ⚠️ Partial |
| Resilience & Error Handling | 5 | ⚠️ Partial |

---

## 1. Testing — Unit Tests (Agent Core)

### 1.1 Existing Tests ✅

| Test File | Covers | Lines |
|-----------|--------|------:|
| `tests/unit/test_agent_mesh.py` | A2A mesh routing, circuit breakers | 8,728 |
| `tests/unit/test_blob_client.py` | Blob Storage operations | 4,179 |
| `tests/unit/test_clinical_retriever.py` | Clinical retriever tool calls | 5,622 |
| `tests/unit/test_commercial_retriever.py` | Commercial retriever tool calls | 6,934 |
| `tests/unit/test_graph_client.py` | Neo4j + Gremlin dual-backend | 4,886 |
| `tests/unit/test_keyvault_resolver.py` | Key Vault secret resolution | 4,463 |
| `tests/unit/test_legal_retriever.py` | Legal retriever tool calls | 6,275 |
| `tests/unit/test_llm_cache.py` | LLM response caching | 3,581 |
| `tests/unit/test_message_broker.py` | Kafka/SB broker abstraction | 4,546 |
| `tests/unit/test_ner_service.py` | NER service (Azure + regex) | 4,156 |
| `tests/unit/test_rag_pipeline.py` | RAG chunking + retrieval | 13,067 |
| `tests/unit/test_redis_client.py` | Redis client operations | 4,192 |
| `tests/unit/test_social_retriever.py` | Social retriever tool calls | 6,820 |
| `tests/unit/test_websocket.py` | WebSocket + PubSub manager | 5,175 |
| `tests/test_models.py` | Pydantic schemas & enums | 10,379 |
| `tests/test_integration.py` | Cross-service integration | 10,851 |
| `tests/test_e2e_keytruda.py` | E2E Keytruda scenario | 9,309 |

### 1.2 Missing Tests — Must Create ❌

- [ ] **Planner Agent — `test_decomposer.py`**
  - `IntentDecomposer.decompose()` with mocked Azure OpenAI responses
  - Edge cases: ambiguous query (clarification request), empty tasks, malformed JSON
  - Retry behavior on `httpx.HTTPError` and `json.JSONDecodeError` (tenacity)
  - Pillar routing correctness (LEGAL, CLINICAL, COMMERCIAL, SOCIAL, KNOWLEDGE)

- [ ] **Planner Agent — `test_publisher.py`**
  - `TaskPublisher.publish()` session creation in Cosmos DB
  - Service Bus message routing per pillar type
  - Audit trail entries for `SESSION_CREATED`, `TASK_PUBLISHED`, `TASK_GRAPH_GENERATED`
  - Partial publish failure (some tasks fail, others succeed)
  - Correlation ID propagation

- [ ] **Supervisor Agent — `test_validator.py`**
  - `GroundingValidator.validate()` two-pass validation (rule-based + LLM)
  - Grounding score calculation (0.0–1.0 range)
  - Rule-based conflict detection (`_detect_rule_based_conflicts`)
  - LLM-as-judge mode with mocked OpenAI response
  - Edge case: zero agent results, missing citations

- [ ] **Supervisor Agent — `test_conflict_resolver.py`**
  - `ConflictResolver.resolve()` severity-based resolution routing
  - AUTO_RESOLVED for LOW severity
  - ANNOTATED for MEDIUM severity
  - ESCALATED for CRITICAL severity (Teams webhook)
  - `_send_teams_card()` with mocked HTTP client

- [ ] **Executor Agent — `test_report_generator.py`**
  - `ReportGenerator.generate_report()` with mocked session data
  - Context-constrained decoding (verify no parametric memory leakage)
  - `_determine_decision()` deterministic GO/NO-GO logic
  - Edge cases: missing pillars, empty findings, no validation data

- [ ] **Executor Agent — `test_chart_generator.py`**
  - `generate_revenue_chart()` with valid and empty revenue data
  - `generate_patent_timeline()` with valid and empty patent lists
  - `generate_safety_gauge()` with all risk levels (LOW/MEDIUM/HIGH/CRITICAL)
  - Base64 output format validation
  - Matplotlib non-interactive backend (`Agg`) assertion

- [ ] **Executor Agent — `test_pdf_engine.py`**
  - `PDFEngine.render_pdf()` HTML template rendering
  - `_markdown_to_html()` conversion fidelity
  - `_build_citation_rows()` HTML table generation
  - `upload_to_blob()` with mocked Blob Storage client
  - Cover page: query, decision badge, meta info

- [ ] **Quality Evaluator — `test_quality_evaluator.py`**
  - `QualityEvaluator.evaluate()` scoring dimensions (accuracy, citation, relevance)
  - Weighted overall score calculation (0.5, 0.3, 0.2 weights)
  - Pass/fail threshold (`QUALITY_THRESHOLD = 0.6`)
  - Fail-open behavior (evaluator failure → pass through)

- [ ] **Prompt Enhancer — `test_prompt_enhancer.py`**
  - `PromptEnhancer.enhance()` with mocked OpenAI
  - Strategy classification (specificity, constraints, decompose, rephrase)
  - Fallback behavior (enhancement failure → original prompt)

- [ ] **SPAR Reflection — `test_reflect.py`**
  - `ReflectionEngine.reflect_on_session()` full reflection lifecycle
  - `_check_citation_validity()` dead-link detection
  - `_check_timeouts_and_failures()` DLQ and timeout detection
  - `_check_decision_consistency()` evidence alignment
  - `_check_pillar_coverage()` missing pillar detection
  - Dynamic thresholds via user preferences

- [ ] **MCP Server — `test_mcp_server.py`**
  - Input validation for all 8 tools (Pydantic `ConfigDict(extra="forbid")`)
  - `pharma_create_session` → Planner API call
  - `pharma_get_session` → session retrieval
  - Resource reads (`pharma://sessions/{id}`, `pharma://agents/active`)
  - Error formatting consistency (`_err()`)
  - Rate limiting per MCP client

- [ ] **ML Pipeline — `test_dpo_training.py`**
  - `DPODataCollector.collect_from_session()` pair generation
  - `DPODataCollector.export_to_jsonl()` JSONL format compliance
  - `DPOTrainer.validate_data()` data quality checks
  - `DPOTrainer.load_data()` file parsing

---

## 2. Testing — Integration & E2E

### 2.1 Existing ✅
- `tests/test_integration.py` — Cross-service integration tests
- `tests/test_e2e_keytruda.py` — E2E flow for Keytruda (single scenario)

### 2.2 Missing ❌

- [ ] **Multi-Drug E2E Scenarios**
  - Keytruda is the only drug with an E2E test
  - Need scenarios for: Semaglutide (Ozempic), Paxlovid, generic drugs, orphan drugs
  - Each should validate the full flow: Planner → Retrievers → Supervisor → Executor → PDF

- [ ] **Negative Path E2E Tests**
  - Circuit breaker trip → DLQ → session completes with partial data
  - All external APIs down → explicit `DATA_UNAVAILABLE` propagation
  - LLM timeout → retry → eventual success or graceful degradation
  - Invalid query → clarification request flow

- [ ] **Docker Compose Integration Test**
  - Bring up full stack (`docker compose up`)
  - Submit query via Planner API
  - Verify end-to-end message flow through Kafka topics
  - Validate Cosmos DB session lifecycle
  - Verify PDF generation and Blob upload

- [ ] **A2A Mesh Integration Test**
  - Quality Evaluator ↔ Retriever interaction
  - Prompt Enhancer re-dispatch after quality failure
  - Circuit breaker behavior across mesh tiers

---

## 3. Testing — Performance & Load

- [ ] **Latency Benchmarks**
  - End-to-end time per query (target: <5 minutes)
  - Per-retriever execution time with real APIs
  - LLM call latency (decompose, validate, report, quality eval, enhance)
  - PDF generation + Blob upload time

- [ ] **Load Testing (Locust/k6)**
  - 10 concurrent queries → validate KEDA scaling
  - 100 concurrent queries → stress test Service Bus throughput
  - Cosmos DB RU consumption under load

- [ ] **Memory & Resource Profiling**
  - matplotlib figure cleanup (no memory leaks in chart generation)
  - Redis memory pressure under 10K concurrent sessions
  - Connection pool sizing: asyncpg pool, httpx pool, AMQP senders

---

## 4. Infrastructure — K8s Deployment Manifests

### 4.1 Existing ✅
- `infra/k8s/base/planner-deployment.yaml`
- `infra/k8s/base/supervisor-deployment.yaml`
- `infra/k8s/base/executor-deployment.yaml`
- `infra/k8s/base/namespace.yaml`
- `infra/k8s/base/configmap.yaml`
- `infra/k8s/base/kustomization.yaml`

### 4.2 Missing Deployment Manifests ❌
- [ ] `retriever-legal-deployment.yaml`
- [ ] `retriever-clinical-deployment.yaml`
- [ ] `retriever-commercial-deployment.yaml`
- [ ] `retriever-social-deployment.yaml`
- [ ] `retriever-knowledge-deployment.yaml`
- [ ] `retriever-news-deployment.yaml`
- [ ] `quality-evaluator-deployment.yaml`
- [ ] `prompt-enhancer-deployment.yaml`
- [ ] `celery-worker-deployment.yaml`
- [ ] `celery-beat-deployment.yaml`
- [ ] `mcp-server-deployment.yaml`
- [ ] `frontend-deployment.yaml` + `Service` + `Ingress`

### 4.3 Missing KEDA ScaledObjects ❌
- [ ] `retriever-commercial-scaler` (ScaledObject for `pharma.tasks.commercial`)
- [ ] `retriever-social-scaler` (ScaledObject for `pharma.tasks.social`)
- [ ] `retriever-knowledge-scaler` (ScaledObject for `pharma.tasks.knowledge`)

### 4.4 Missing K8s Resources ❌
- [ ] `HorizontalPodAutoscaler` for Planner, Supervisor, Executor (CPU-based fallback)
- [ ] `PodDisruptionBudget` for each stateless agent
- [ ] `NetworkPolicy` restricting inter-pod traffic to required flows only
- [ ] `ResourceQuota` for `pharma-ai` namespace
- [ ] Update `kustomization.yaml` to include all new manifests

---

## 5. Infrastructure — Bicep IaC

### 5.1 Existing ✅
- Azure OpenAI (GPT-4o + embedding deployment)
- Cosmos DB (NoSQL + Gremlin, sessions + audit containers)
- Service Bus (6 topic definitions)
- Azure AI Search (standard SKU + semantic reranking)
- Azure Cache for Redis
- Azure DB for PostgreSQL Flexible Server
- Blob Storage
- Key Vault
- AI Language (NER)
- Web PubSub
- Application Insights

### 5.2 Missing Bicep Resources ❌
- [ ] **Event Hubs namespace** + 6 event hubs (KEDA triggers reference Event Hubs but no Bicep resource)
- [ ] **Container App Environment** + individual container app definitions for each agent
- [ ] **Log Analytics Workspace** (referenced by App Insights but not explicitly declared)
- [ ] **Managed Identity** (user-assigned) for agent services → Key Vault, Cosmos, Service Bus access

### 5.3 Bicep Improvements ❌
- [ ] Add `dependsOn` for cross-resource references (e.g., App Insights → Log Analytics)
- [ ] Parameterize SKU tiers for dev vs. prod (e.g., Redis `C0` for dev, `C1` for prod)
- [ ] Add `tags` to all resources for cost tracking
- [ ] Add Key Vault secret seeding (OpenAI key, Cosmos key, SB connection string)
- [ ] Add role assignments (RBAC) for Managed Identity

---

## 6. Database & Migrations

### 6.1 Existing ✅
- `infra/migrations/001_initial.py` — PostgreSQL schema (sessions, audit, analytics tables)
- `infra/db/init/` — Docker init scripts for local dev

### 6.2 Missing ❌
- [ ] **Alembic migration framework** — `alembic.ini`, `alembic/env.py`, versioned migrations
- [ ] **Schema versioning** for tables: `reflection_log`, `agent_registry`, `audit`, `memory`, `task_analytics`, `agent_result_analytics`
- [ ] **Cosmos DB index policies** — composite indexes for:
  - Session queries by user_id + status
  - Audit trail queries by session_id + timestamp
  - Stored procedures for atomic multi-document transactions (if needed)

---

## 7. Secrets Management & Security

### 7.1 Current State ⚠️
- Key Vault declared in Bicep ✅
- `.env` file contains raw credentials ❌
- No Managed Identity assignments ❌

### 7.2 Pending Secrets Work ❌
- [ ] Migrate all `.env` credentials to Azure Key Vault secrets
- [ ] Create `keyvault_resolver.py` integration in container startup (already exists but needs wiring)
- [ ] Add Managed Identity assignments for agent Container Apps/AKS pods
- [ ] Remove secrets from K8s `secrets.template.yaml` → use CSI Secret Store driver

### 7.3 Security Hardening ❌
- [ ] **Authentication** — Add Azure Entra ID token validation middleware to Planner FastAPI
- [ ] **Authorization** — RBAC: admin vs. analyst role separation
- [ ] **API Rate Limiting** — Per-user rate limits on `POST /api/v1/sessions` (already have `rate_limit.py` but needs enforcement)
- [ ] **Input Sanitization** — Validate query inputs for injection (SQL, Gremlin, prompt injection)
- [ ] **CORS Hardening** — Replace wildcard `allow_origins=["*"]` with explicit frontend domain
- [ ] **Dependency Audit** — Run `pip-audit` and `npm audit` in CI

---

## 8. CI/CD Pipeline

### 8.1 Current State ✅
The `ci-cd.yaml` (248 lines, 8 jobs) includes:
- Lint & type check (Ruff + mypy)
- Unit tests with coverage
- Integration tests (Docker Compose services)
- Security scanning (Bandit, pip-audit, Trivy)
- Frontend lint + build
- Docker build & push (build matrix for all targets)
- Frontend image build
- Deploy to AKS

The old `ci.yml` (62 lines) is a simpler pipeline.

### 8.2 Missing / Needs Refinement ❌
- [ ] **Remove duplicate `ci.yml`** — only `ci-cd.yaml` should be active
- [ ] **Docker build matrix validation** — Verify matrix targets match all services:
  - `planner`, `supervisor`, `executor`, `retriever-workers`, `celery-worker`, `mcp-server`
  - Confirm Dockerfile multi-stage build targets exist for each
- [ ] **E2E test stage** — Add post-deploy smoke test step (hit Planner `/health` after AKS deploy)
- [ ] **Canary deployment** — Progressive rollout instead of full `kubectl apply`
- [ ] **Artifact caching** — Cache `pip install` and `npm ci` between jobs for speed

---

## 9. API & Data Quality

### 9.1 Real API Status ✅
All retrievers now call real external APIs. Mock data has been removed.

| Retriever | Real APIs | Fallback |
|-----------|-----------|----------|
| **Legal** | USPTO Orange Book, IPO (scraped) | `DATA_UNAVAILABLE` for IPO |
| **Clinical** | ClinicalTrials.gov v2, FDA approvals, CDSCO (scraped) | `DATA_UNAVAILABLE` for CDSCO |
| **Commercial** | SEC EDGAR, Yahoo Finance, TAM estimation | Estimation model fallback |
| **Social** | FDA FAERS, PubMed E-utilities, composite sentiment | Partial result |
| **Knowledge** | Azure AI Search RAG pipeline | Empty context |
| **News** | Tavily search API | Empty news |

### 9.2 Remaining Data Quality Work ❌
- [ ] **Knowledge Retriever RAG Index Population**
  - Azure AI Search indexes need to be seeded with internal pharma documents
  - Currently empty → Knowledge retriever returns no RAG context
  - Need: sample document corpus + ingestion pipeline run

- [ ] **Commercial Data Enrichment**
  - SEC EDGAR and Yahoo Finance provide limited pharma-specific data
  - Consider: IQVIA integration (requires license), GlobalData API
  - MVP: Document data limitations in report output

- [ ] **Social Sentiment Pipeline**
  - PubMed E-utilities is the primary sentiment source — functional
  - Twitter/X healthcare API, Reddit medical subs → not integrated
  - MVP: Document limited social coverage in report

- [ ] **IPO/CDSCO Scraper Robustness**
  - Both return `DATA_UNAVAILABLE` on failure — correct behavior
  - Need: periodic monitoring of scraper success rates
  - Consider: third-party data providers as a premium tier

---

## 10. Observability & Monitoring

### 10.1 Existing ✅
- OpenTelemetry setup with Azure Monitor and Jaeger (local)
- `PharmaMetrics` class: session counter, task completion/failure, circuit breaker trips, LLM usage/latency
- Structured logging via `structlog`
- FastAPI auto-instrumentation
- Span enrichment with `session_id`, `pillar`, `agent_type`, `task_id`

### 10.2 Missing ❌
- [ ] **Dashboard Templates** — Azure Monitor workbook / Grafana dashboard JSON
  - Session throughput over time
  - Per-pillar execution time distribution
  - LLM token usage breakdown
  - Circuit breaker trip frequency
  - Error rate by agent type

- [ ] **Alert Rules** — Azure Monitor action groups
  - Alert on circuit breaker trips > 3/hour
  - Alert on Cosmos DB 429 (throttling)
  - Alert on LLM latency P99 > 30s
  - Alert on Service Bus DLQ depth > 10

- [ ] **Distributed Trace Completeness**
  - Verify trace propagation: Planner → Service Bus → Retriever → Cosmos → Supervisor → Executor
  - Ensure correlation IDs flow through all async boundaries
  - Add span attributes for business context (drug_name, decision, grounding_score)

- [ ] **Audit Trail Query API**
  - `GET /api/v1/sessions/{id}/audit` endpoint in Planner main.py
  - Currently audit is written but not exposed via API

- [ ] **Health Check Depth**
  - Current health checks return `{"status": "healthy"}` without dependency checks
  - Add deep health: Cosmos DB ping, Redis ping, Service Bus connection, LLM endpoint reachability

---

## 11. Frontend Polish

### 11.1 Current State ✅
- Main dashboard page (`page.tsx`) — 18,923 bytes, live API wiring
- Admin page (`admin/page.tsx`) — exists
- Reports page (`reports/`) — exists
- Layout + nav links
- Global CSS (16,405 bytes)

### 11.2 Pending ❌
- [ ] **Reports Page — PDF Download**
  - Wire `GET /sessions?status=COMPLETED` to list completed reports
  - Add PDF download link from `report_url` field
  - Show decision badge (GO/NO-GO/CONDITIONAL) per session

- [ ] **Admin Page — System Health Dashboard**
  - Wire to system health endpoints (deep health checks)
  - Audit trail viewer with pagination
  - Agent registry status (which agents are alive)
  - KEDA scaling metrics visualization

- [ ] **Real-Time Session Updates**
  - WebSocket connection to `ws://planner:8000/ws/{session_id}`
  - Live progress indicators as each retriever completes
  - Toast notifications for validation pass/fail

- [ ] **Error & Loading States**
  - Skeleton loaders during API calls
  - Error boundaries with retry actions
  - Empty states for zero sessions

---

## 12. MCP Server Hardening

### 12.1 Current State ✅
- 8 tools declared with Pydantic input validation
- HTTP-based Planner API calls
- Resource reads for sessions and agents
- Lifespan management for HTTP client

### 12.2 Pending ❌
- [ ] **Authentication/Authorization**
  - Add API key validation for MCP tool calls
  - Per-client rate limiting (separate from user-facing rate limits)
  - Audit logging for MCP tool invocations

- [ ] **Error Handling Tests**
  - Each tool's error path (404, 500, timeout, validation failure)
  - `_err()` format consistency across all tools

- [ ] **Resource Subscriptions (SSE)**
  - Real-time session status updates via SSE/WebSocket
  - `pharma://sessions/{id}/status` subscription
  - Integration tests validating MCP protocol compliance

- [ ] **Tool Coverage Gaps**
  - `pharma_compare_drugs` — side-by-side drug analysis
  - `pharma_graph_query` — knowledge graph traversal via MCP
  - `pharma_export_session` — JSONL/CSV export

---

## 13. ML Pipeline (DPO Fine-Tuning)

### 13.1 Current State ✅
- `DPODataCollector` — collects chosen/rejected pairs from production sessions
- `DPOTrainer` — supports Azure OpenAI fine-tuning and local TRL training
- CLI entry point: `python -m src.ml.dpo_training`
- JSONL export format compatible with OpenAI and HuggingFace TRL

### 13.2 Pending ❌
- [ ] **Unit Tests** — `tests/unit/test_dpo_training.py` (see §1.2)
- [ ] **Celery Beat Task Wiring**
  - Reference: `celery_ingestion_tasks.py` has RAG ingestion tasks but no DPO tasks
  - Need: weekly Celery Beat task for extracting DPO pairs from completed sessions
- [ ] **Model Evaluation Pipeline**
  - A/B testing framework: GPT-4o vs. fine-tuned model
  - Evaluation metrics: grounding score improvement, hallucination rate
  - Automated benchmarking on test drug queries
- [ ] **Model Registry**
  - Version tracking for fine-tuned models
  - Rollback capability (switch between model versions)
  - Integration with QualityEvaluator for automatic model selection
- [ ] **Training Data Curation**
  - Minimum corpus size before first training run (target: 500+ pairs)
  - Data quality filters: min grounding score, min citation count

---

## 14. Resilience & Error Handling

### 14.1 Current Patterns ✅
- Circuit breaker in `BaseRetriever` (failure threshold: 3, cooldown: 60s)
- Redis-backed circuit breaker in `AgentMesh`
- Retry with exponential backoff in `IntentDecomposer` (tenacity)
- DLQ routing for failed Service Bus messages
- Fail-open in audit trail (never crash the agent)
- Explicit `DATA_UNAVAILABLE` instead of silent mock fallback

### 14.2 Pending ❌
- [ ] **Idempotency Guards**
  - Service Bus message deduplication (message ID checks)
  - Cosmos DB conditional writes (ETag-based) — exists for `update_task_status` but not all operations
  - Idempotent Celery tasks (prevent duplicate PDF generation)

- [ ] **Graceful Degradation Documentation**
  - Document the exact degradation path for each external dependency failure
  - Create a degradation matrix: which features remain available when each component is down

- [ ] **Timeout Configuration Review**
  - `httpx.Client(timeout=60.0)` in decomposer — appropriate?
  - Execution timeout in base retriever — configurable per pillar?
  - Service Bus `max_wait_time=30` — tune for production throughput

- [ ] **Dead Letter Queue Processing**
  - Runbook for manual DLQ inspection and replay
  - Automated DLQ alerting (alert when depth > threshold)
  - Retry mechanism for DLQ messages (with backoff)

- [ ] **Session Timeout Enforcement**
  - `APP_SESSION_TIMEOUT_SECONDS = 600` (10 min) declared in config
  - Need: Celery Beat task to mark stale `RETRIEVING` sessions as `TIMED_OUT`
  - Frontend should show timeout state

---

## 15. Performance Optimization

### 15.1 Current Optimizations ✅
- AMQP sender caching in Service Bus publisher (eliminates 50ms/message overhead)
- Redis LLM response cache with TTL
- Async HTTP client pooling in agent mesh
- Batch audit writes (deque buffer, flush on threshold or timer)
- Cosmos DB partial update (`_patch_session`) instead of full replace

### 15.2 Pending ❌
- [ ] **Connection Pool Sizing**
  - asyncpg pool: current defaults → benchmark and tune `min_size`/`max_size`
  - httpx async client: `limits` not explicitly configured
  - Service Bus: one sender per topic is good; verify no connection leaks

- [ ] **Retriever Parallelism**
  - 6 retrievers run in parallel (via Service Bus) ✅
  - Within each retriever: some tools could run concurrently (e.g., `orange_book_search` + `patent_expiry_analysis` in Legal)
  - Measure: is per-retriever sequential tool execution a bottleneck?

- [ ] **LLM Token Optimization**
  - Decomposer: `max_tokens=2000` — audit actual token usage, reduce if wasteful
  - Report Generator: `max_tokens=4000` — benchmark against actual report lengths
  - Quality Evaluator: `max_tokens=500` — appropriate for scoring
  - Consider: GPT-4o-mini for evaluation and enhancement (cost savings)

- [ ] **Cosmos DB RU Optimization**
  - Audit container: writes are append-only → verify indexing policy excludes unnecessary fields
  - Session container: reads dominate → add composite indexes for common query patterns
  - Monitor: point reads vs. cross-partition queries

- [ ] **Caching Strategy**
  - Drug-specific query caching: same drug queried multiple times → cache retriever results
  - RAG retrieval caching: same drug+pillar → cache for TTL
  - Currently: LLM cache exists but retriever result caching is minimal

- [ ] **PDF Generation**
  - WeasyPrint is heavy (~500MB Docker layer)
  - Measure: PDF generation time for typical reports
  - Consider: async PDF generation via Celery (already wired) → ensure it's activated

---

## 16. Documentation

### 16.1 Existing ✅
- `README.md` — comprehensive project overview (201 lines)
- `agents.md` — agent architecture documentation
- `claude.md` — Claude context file
- `docs/adr.md` — 3 Architecture Decision Records
- `docs/runbook.md` — operational runbook (126 lines)

### 16.2 Pending ❌
- [ ] **OpenAPI Specification**
  - Planner API (FastAPI auto-generates, but not published/versioned)
  - Need: export `openapi.json` and version it in the repo
  - Add Swagger UI deployment or static docs page

- [ ] **Additional ADRs Needed**
  - ADR-004: Kafka vs. Service Bus routing decision
  - ADR-005: DPO training strategy (Azure fine-tune vs. local TRL)
  - ADR-006: RAG indexing strategy (per-pillar vs. unified index)
  - ADR-007: Multi-agent quality loop (Evaluator → Enhancer → Retry)

- [ ] **API Integration Guide**
  - Document all external API dependencies with:
    - API endpoint URLs
    - Authentication requirements
    - Rate limits
    - Response formats
    - Known limitations (IPO, CDSCO scraping)

- [ ] **Deployment Guide**
  - Step-by-step Azure deployment from scratch
  - Bicep parameter file examples for dev/staging/prod
  - AKS cluster setup (node pools, KEDA operator)
  - DNS and TLS configuration

- [ ] **Developer Onboarding Guide**
  - Local development setup (Docker Compose)
  - Environment variable reference (`.env.example` mapping)
  - Test execution instructions
  - Code style and contribution guidelines

---

## 17. Docker & Containerization

### 17.1 Current State ✅
- `Dockerfile` (root) — multi-stage, 2,047 bytes
- `src/agents/planner/Dockerfile` — Planner-specific
- `src/agents/retrievers/Dockerfile` — Retriever-specific
- `src/frontend/Dockerfile` — Next.js frontend
- `docker-compose.yml` — 17 services, production-grade

### 17.2 Pending ❌
- [ ] **Dockerfile Build Targets Audit**
  - Verify multi-stage build targets exist for all CI matrix entries
  - Ensure `--target` for: `planner`, `supervisor`, `executor`, `retriever-workers`, `celery-worker`, `mcp-server`

- [ ] **Image Size Optimization**
  - WeasyPrint adds ~300MB — consider extracting PDF generation into a dedicated lightweight service
  - Verify `.dockerignore` excludes: `tests/`, `docs/`, `*.md`, `.git/`, `node_modules/`

- [ ] **Container Security**
  - Run as non-root user (verify `USER` directive in all Dockerfiles)
  - Pin base image versions (not `:latest`)
  - Trivy scan in CI (already configured in `ci-cd.yaml`)

---

## 18. Azure End-to-End Readiness

> **This is the most critical section.** Everything in the codebase is built for Azure, but numerous wiring gaps prevent the system from actually running on Azure services. This section covers every Azure touchpoint that needs work.

### 18.1 Azure Feature Flag Checklist

The codebase uses **7 feature flags** to toggle between local dev and Azure services. For production, ALL must be enabled and their corresponding Azure resources provisioned.

| Feature Flag | Env Var | Default | Azure Service | Code Location | Status |
|--------------|---------|---------|---------------|---------------|--------|
| Azure Redis | `REDIS_USE_AZURE=true` | `false` | Azure Cache for Redis | `redis_client.py:71` | ✅ Code ready, needs config |
| Azure PostgreSQL | `POSTGRES_USE_AZURE_AD=true` | `false` | Azure DB for PostgreSQL | `postgres_client.py:87` | ✅ Code ready, needs config |
| Azure Monitor | `TELEMETRY_USE_AZURE_MONITOR=true` | `false` | Application Insights | `telemetry.py:169` | ✅ Code ready, needs config |
| Azure Web PubSub | `WEB_PUBSUB_USE_AZURE=true` | `false` | Azure Web PubSub | `websocket.py:342` | ✅ Code ready, needs config |
| Cosmos Gremlin | `GREMLIN_USE_GREMLIN=true` | `false` | Cosmos DB Gremlin API | `graph_client.py:56` | ✅ Code ready, needs config |
| Event Hubs | `KAFKA_USE_EVENT_HUBS=true` | `false` | Azure Event Hubs | `kafka_client.py:54` | ⚠️ Code ready, **no Bicep resource** |
| NER Azure | *(auto-detected)* | regex fallback | Azure AI Language | `ner_service.py:82` | ✅ Auto-detects from config |

**Action Required:**
- [ ] Create `.env.production` with all 7 flags set to `true`
- [ ] Validate each flag's code path with an Azure integration test
- [ ] Document the exact toggle behavior in the operational runbook

### 18.2 Key Vault Startup Wiring — CRITICAL GAP ❌

**The Problem:** `keyvault_resolver.py` exists and is fully implemented (17 secrets mapped), but **no agent calls `resolve_secrets_from_keyvault()` at startup**.

```python
# keyvault_resolver.py — _SECRET_MAP (17 secrets)
"azure-openai-api-key"          → AZURE_OPENAI_API_KEY
"cosmos-db-key"                  → COSMOS_DB_KEY
"service-bus-connection-string"  → SERVICE_BUS_CONNECTION_STRING
"blob-storage-connection-string" → BLOB_STORAGE_CONNECTION_STRING
"ai-search-api-key"             → AI_SEARCH_API_KEY
"redis-url"                      → REDIS_URL
"postgres-url"                   → POSTGRES_URL
"web-pubsub-connection-string"   → WEB_PUBSUB_CONNECTION_STRING
"gremlin-key"                    → GREMLIN_KEY
"tavily-api-key"                 → TAVILY_API_KEY
"telemetry-connection-string"    → TELEMETRY_APPLICATION_INSIGHTS_CONNECTION_STRING
# ... and 6 more
```

**Impact:** In production, agents read from `.env` (contains raw credentials) instead of Key Vault. This is a **compliance violation** (FDA 21 CFR Part 11 requires secrets management).

- [ ] **Wire Key Vault resolver into every agent's startup sequence**
  - `planner/main.py` — call `resolve_secrets_from_keyvault()` before `get_settings()` in `lifespan()`
  - `supervisor/main.py` — same pattern
  - `executor/main.py` — same pattern
  - `base_retriever.py` — call in `start()` lifecycle before config load
  - `quality_evaluator/main.py` — same pattern
  - `prompt_enhancer/main.py` — same pattern
  - `mcp_server.py` — call in `_lifespan()` before HTTP client init

- [ ] **Create a shared bootstrap function**
  ```python
  # src/shared/bootstrap.py
  def bootstrap_agent():
      resolve_secrets_from_keyvault()  # Always first
      settings = get_settings()        # Now picks up KV secrets
      setup_telemetry(settings)        # OTel init
      return settings
  ```

- [ ] **Seed Key Vault with actual secrets** — `az keyvault secret set` for all 17 mapped secrets
- [ ] **Test:** verify agent starts correctly with `KEY_VAULT_URL` set and no `.env` file

### 18.3 Service Bus — Subscriptions Missing from Bicep ❌

**The Problem:** The `ServiceBusConsumer` requires topic **subscriptions** (`get_subscription_receiver(topic_name, subscription_name)`), but Bicep only provisions **topics** — no subscriptions.

**Impact:** Consumers fail at startup because the subscription doesn't exist.

| Topic (Bicep ✅) | Subscription Needed | Consumer |
|------------------|--------------------|---------|
| `legal-tasks` | `retriever-legal-sub` | Legal Retriever |
| `clinical-tasks` | `retriever-clinical-sub` | Clinical Retriever |
| `commercial-tasks` | `retriever-commercial-sub` | Commercial Retriever |
| `social-tasks` | `retriever-social-sub` | Social Retriever |
| `knowledge-tasks` | `retriever-knowledge-sub` | Knowledge Retriever |
| `news-tasks` | `retriever-news-sub` | News Retriever |

- [ ] **Add subscription resources to `infra/bicep/main.bicep`** for each topic:
  ```bicep
  resource legalSub 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = {
    parent: topics[0]
    name: 'retriever-legal-sub'
    properties: {
      maxDeliveryCount: 5
      deadLetteringOnMessageExpiration: true
      lockDuration: 'PT1M'
    }
  }
  ```
- [ ] **Add DLQ subscription** for each topic (dead letter monitoring)
- [ ] **Verify `subscription_name` in each retriever's `main.py`** matches the Bicep resource name

### 18.4 Service Bus — News Topic Missing from Publisher ❌

**The Problem:** `ServiceBusPublisher._topic_map` maps 5 pillars but **excludes `PillarType.NEWS`**:
```python
# servicebus_client.py:58-64 — NEWS is missing!
self._topic_map = {
    PillarType.LEGAL: settings.servicebus.legal_topic,
    PillarType.CLINICAL: settings.servicebus.clinical_topic,
    PillarType.COMMERCIAL: settings.servicebus.commercial_topic,
    PillarType.SOCIAL: settings.servicebus.social_topic,
    PillarType.KNOWLEDGE: settings.servicebus.knowledge_topic,
    # PillarType.NEWS: ??? — NOT HERE
}
```

**Impact:** News retriever tasks published by the Planner raise `KeyError` — the News pillar never executes.

- [ ] **Add `news_topic` to `ServiceBusConfig`** in `config.py` (currently only 5 topics defined)
- [ ] **Add `PillarType.NEWS` to `ServiceBusPublisher._topic_map`** in `servicebus_client.py`
- [ ] **Add `PillarType.NEWS` to `ServiceBusConsumer.topic_map`** (same file, line ~233)
- [ ] **Add `news-tasks` topic to the Bicep loop** (already in `infra/bicep/main.bicep` ✅, but verify `infra/main.bicep`)

### 18.5 Bicep IaC Consolidation — Two Conflicting Files ❌

**The Problem:** There are **two** Bicep files with different resource sets:

| File | Resources | Lines | Status |
|------|-----------|------:|---------|
| `infra/main.bicep` | Cosmos (Serverless), SB (5 topics), KV, Blob, **Container Apps Env**, **Log Analytics** | 149 | Legacy |
| `infra/bicep/main.bicep` | OpenAI, Cosmos (Standard), SB (6 topics), KV, Blob, Redis, PostgreSQL, AI Search, AI Language, Web PubSub, App Insights | 277 | Production |

**Impact:** Deploying the wrong file provisions the wrong resources. Neither file is complete.

- [ ] **Merge into a single `infra/bicep/main.bicep`** containing ALL resources from both files:
  - From `infra/main.bicep`: Container Apps Environment, Log Analytics Workspace, Blob `reports` container
  - From `infra/bicep/main.bicep`: Everything else (it's more complete)
  - Delete `infra/main.bicep` after merge

- [ ] **Missing resources in the merged Bicep:**

  | Resource | Why Needed | Service That Uses It |
  |----------|------------|---------------------|
  | **Event Hubs Namespace** + 6 event hubs | KEDA scalers reference Event Hubs, Kafka client uses Event Hubs in prod | `kafka_client.py`, `scaled-objects.yaml` |
  | **Container App definitions** (15 services) | Each agent needs a Container App resource | All agents |
  | **User-Assigned Managed Identity** | Passwordless auth to KV, Cosmos, SB, Blob, Redis, PG | All agents |
  | **RBAC Role Assignments** (12+ assignments) | MI → Key Vault Secrets User, MI → Cosmos DB Data Contributor, etc. | All agents |
  | **Cosmos DB Gremlin Database + Graph** | Knowledge Graph container | `graph_client.py` |
  | **Service Bus Topic Subscriptions** (6) | Consumer receiver pattern | All retrievers |
  | **Private Endpoints** (per README: zero public endpoints) | Network isolation | All services |
  | **Azure Container Registry (ACR)** | Docker image storage | CI/CD pipeline |
  | **AKS Cluster** (if K8s path instead of Container Apps) | Kubernetes hosting | All agents |
  | **DNS Zone** + **TLS Certificate** | HTTPS frontend | Frontend |

### 18.6 Managed Identity & RBAC — Nothing Assigned ❌

**The Problem:** Code uses `DefaultAzureCredential()` (in `keyvault_resolver.py`, `redis_client.py`, `postgres_client.py`), which works with Managed Identity. But **no identity is created or assigned** in Bicep.

- [ ] **Create User-Assigned Managed Identity** in Bicep:
  ```bicep
  resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
    name: '${resourceSuffix}-identity'
    location: location
  }
  ```

- [ ] **Assign RBAC roles** for each service:

  | Azure Service | RBAC Role | Role Definition ID |
  |---------------|-----------|--------------------|
  | Key Vault | Key Vault Secrets User | `4633458b-17de-408a-b874-0445c86b69e6` |
  | Cosmos DB | Cosmos DB Built-in Data Contributor | `00000000-0000-0000-0000-000000000002` |
  | Service Bus | Azure Service Bus Data Sender | `69a216fc-b8fb-44d8-bc22-1f3c2cd27a39` |
  | Service Bus | Azure Service Bus Data Receiver | `4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0` |
  | Blob Storage | Storage Blob Data Contributor | `ba92f5b4-2d11-453d-a403-e96b0029c9fe` |
  | Azure Cache for Redis | Redis Cache Contributor | `e0f68234-74aa-48ed-b826-c38b57376e17` |
  | Azure OpenAI | Cognitive Services OpenAI User | `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd` |
  | AI Search | Search Index Data Contributor | `8ebe5a00-799e-43f5-93ac-243d3dce84a7` |
  | AI Language | Cognitive Services Language Reader | `7ef46b58-5511-4524-aa06-4e4a7a3c1842` |
  | Web PubSub | Web PubSub Service Owner | `12cf5a90-567b-43ae-8102-96cf46c7d9b4` |
  | PostgreSQL | *(Azure AD auth, not RBAC)* | — |
  | Event Hubs | Azure Event Hubs Data Sender/Receiver | `2b629674-e913-4c01-ae53-ef4638d8f975` |

- [ ] **Assign MI to Container Apps/AKS pods** so `DefaultAzureCredential()` resolves automatically
- [ ] **Migrate connection strings to passwordless where supported** (Cosmos, Service Bus, Blob, Redis)

### 18.7 Container Apps / AKS Deployment Definitions ❌

**The Problem:** `infra/main.bicep` has a Container Apps Environment but **no Container App resources** — no agents are defined.

- [ ] **Create Container App definitions for all 15 services:**

  | Container App | Image | Port | Min/Max Replicas | Scale Trigger |
  |---------------|-------|:----:|:----------------:|---------------|
  | `planner-agent` | `pharmaai.azurecr.io/planner` | 8000 | 1/5 | HTTP concurrent requests |
  | `supervisor-agent` | `pharmaai.azurecr.io/supervisor` | 8001 | 1/3 | HTTP concurrent requests |
  | `executor-agent` | `pharmaai.azurecr.io/executor` | 8002 | 1/3 | HTTP concurrent requests |
  | `retriever-legal` | `pharmaai.azurecr.io/retriever-workers` | — | 0/10 | Service Bus queue length |
  | `retriever-clinical` | `pharmaai.azurecr.io/retriever-workers` | — | 0/20 | Service Bus queue length |
  | `retriever-commercial` | `pharmaai.azurecr.io/retriever-workers` | — | 0/10 | Service Bus queue length |
  | `retriever-social` | `pharmaai.azurecr.io/retriever-workers` | — | 0/10 | Service Bus queue length |
  | `retriever-knowledge` | `pharmaai.azurecr.io/retriever-workers` | — | 0/5 | Service Bus queue length |
  | `retriever-news` | `pharmaai.azurecr.io/retriever-workers` | — | 0/5 | Service Bus queue length |
  | `quality-evaluator` | `pharmaai.azurecr.io/quality-evaluator` | — | 1/3 | HTTP |
  | `prompt-enhancer` | `pharmaai.azurecr.io/prompt-enhancer` | — | 1/3 | HTTP |
  | `celery-worker` | `pharmaai.azurecr.io/celery-worker` | — | 1/10 | Service Bus queue length |
  | `celery-beat` | `pharmaai.azurecr.io/celery-worker` | — | 1/1 | None (singleton) |
  | `mcp-server` | `pharmaai.azurecr.io/mcp-server` | 8010 | 1/3 | HTTP |
  | `frontend` | `pharmaai.azurecr.io/frontend` | 3000 | 1/5 | HTTP concurrent requests |

- [ ] **Add environment variables for each Container App** — point to Azure services with feature flags enabled
- [ ] **Add secrets references** — pull from Key Vault using MI
- [ ] **Add ingress configuration** for HTTP-facing services (Planner, Frontend, MCP)

### 18.8 Event Hubs — No Bicep Resource ❌

**The Problem:** KEDA `scaled-objects.yaml` references Event Hubs triggers, and `kafka_client.py` supports Event Hubs mode via `KAFKA_USE_EVENT_HUBS=true`. But **no Event Hubs namespace exists in Bicep**.

- [ ] **Add Event Hubs namespace to Bicep:**
  ```bicep
  resource eventHubs 'Microsoft.EventHub/namespaces@2024-01-01' = {
    name: '${resourceSuffix}-eventhubs'
    location: location
    sku: { name: 'Standard', tier: 'Standard', capacity: 1 }
  }
  ```

- [ ] **Add 6 event hubs** (one per pillar) + 3 event hubs (sessions, audit, analytics):
  ```bicep
  var eventHubNames = [
    'pharma.tasks.legal', 'pharma.tasks.clinical', 'pharma.tasks.commercial',
    'pharma.tasks.social', 'pharma.tasks.knowledge', 'pharma.tasks.news',
    'pharma.events.sessions', 'pharma.events.audit', 'pharma.events.analytics'
  ]
  ```

- [ ] **Add consumer groups** per retriever agent (matches KEDA scaler config)
- [ ] **Add checkpoint blob container** (`keda-checkpoints`) to Storage Account
- [ ] **Update KEDA scalers** to match actual Event Hub names

### 18.9 Network Security — Private Link / VNet ❌

**The Problem:** README states "Azure Private Link, zero public endpoints" but **no Private Endpoints exist in Bicep** and no VNet is defined.

- [ ] **Add VNet + Subnets** to Bicep:
  - `aca-subnet` — for Container Apps Environment
  - `private-endpoint-subnet` — for Private Endpoints
  - `postgres-subnet` — delegated to PostgreSQL Flexible Server

- [ ] **Add Private Endpoints** for each Azure service:
  | Service | Private Endpoint Group |
  |---------|------------------------|
  | Cosmos DB | `Sql` |
  | Service Bus | `namespace` |
  | Blob Storage | `blob` |
  | Key Vault | `vault` |
  | Azure AI Search | `searchService` |
  | Azure OpenAI | `account` |
  | Redis | `redisCache` |
  | PostgreSQL | VNet integration (delegated subnet) |
  | Event Hubs | `namespace` |

- [ ] **Add Private DNS Zones** for each service
- [ ] **Disable public network access** on all Azure resources
- [ ] **Add NSG rules** for subnet traffic control

### 18.10 Azure Deployment Checklist (Complete E2E)

**Pre-deployment:**
- [ ] 1. Create Azure Resource Group: `az group create -n pharma-ai-prod-rg -l eastus2`
- [ ] 2. Merge Bicep files (§18.5) into single `infra/bicep/main.bicep`
- [ ] 3. Add all missing resources (§18.5, §18.6, §18.7, §18.8, §18.9)
- [ ] 4. Deploy Bicep: `az deployment group create -g pharma-ai-prod-rg -f infra/bicep/main.bicep`
- [ ] 5. Create ACR: `az acr create -n pharmaai -g pharma-ai-prod-rg --sku Standard`
- [ ] 6. Build & push all Docker images to ACR

**Secret seeding:**
- [ ] 7. Seed all 17 secrets into Key Vault:
  ```bash
  az keyvault secret set --vault-name pharmaai-prod-kv \
    --name azure-openai-api-key --value "<actual-key>"
  # Repeat for all 17 secrets in _SECRET_MAP
  ```

**Agent startup wiring:**
- [ ] 8. Wire `resolve_secrets_from_keyvault()` into all agent lifespans (§18.2)
- [ ] 9. Fix News topic mapping in ServiceBusPublisher (§18.4)

**Feature flag activation:**
- [ ] 10. Create `.env.production` or Container App env vars:
  ```env
  APP_ENV=production
  REDIS_USE_AZURE=true
  REDIS_AZURE_HOST=pharmaai-prod-redis.redis.cache.windows.net
  POSTGRES_USE_AZURE_AD=true
  POSTGRES_SSL_MODE=require
  TELEMETRY_USE_AZURE_MONITOR=true
  WEB_PUBSUB_USE_AZURE=true
  GREMLIN_USE_GREMLIN=true
  KAFKA_USE_EVENT_HUBS=true
  KEY_VAULT_URL=https://pharmaai-prod-kv.vault.azure.net/
  ```

**Data initialization:**
- [ ] 11. Run PostgreSQL migrations: `alembic upgrade head` (§6.2 must be done first)
- [ ] 12. Seed Cosmos DB containers (auto-created by Bicep)
- [ ] 13. Create AI Search indexes: run `IngestionPipeline.initialize()`
- [ ] 14. Ingest sample pharma documents into RAG indexes
- [ ] 15. Seed Knowledge Graph (Cosmos Gremlin): run initial entity ingestion

**Validation:**
- [ ] 16. Verify all agents start with `KEY_VAULT_URL` only (no `.env`)
- [ ] 17. Submit a test query via Planner API
- [ ] 18. Verify message flow: Planner → Service Bus → Retrievers → Cosmos → Supervisor → Executor → Blob → PDF
- [ ] 19. Verify WebSocket updates reach frontend via Web PubSub
- [ ] 20. Verify OpenTelemetry traces appear in Application Insights
- [ ] 21. Verify audit trail entries in Cosmos DB `audit_trail` container
- [ ] 22. Verify PDF report uploaded to Blob Storage with SAS URL

---

## Priority Execution Order

| Phase | Items | Effort | Why First? |
|:---:|--------|:---:|------------|
| **P0** | 🔵 **Azure Key Vault startup wiring (§18.2)** | 🟢 Small | No agent can start securely without this |
| **P0** | 🔵 **Azure Service Bus News topic fix (§18.4)** | 🟢 Small | News pillar completely broken |
| **P0** | 🔵 **Azure Bicep consolidation (§18.5)** — merge 2 files | 🟡 Med | Deploying wrong file provisions wrong resources |
| **P0** | 🔵 **Azure SB subscriptions in Bicep (§18.3)** | 🟢 Small | Consumers fail without subscriptions |
| **P0** | Unit tests for agent core (§1.2) — Planner, Supervisor, Executor | 🟡 Med | Zero test coverage on the 3 most critical services |
| **P0** | Security hardening (§7.3) — Auth, CORS, rate limiting | 🟡 Med | Production launch blocker |
| **P0** | Secrets management (§7.2) — .env → Key Vault | 🟡 Med | Credentials in plaintext |
| **P1** | 🔵 **Azure Managed Identity + RBAC (§18.6)** | 🟡 Med | Passwordless auth required for compliance |
| **P1** | 🔵 **Azure Container Apps or AKS definitions (§18.7)** | 🔴 Large | No deployment target without this |
| **P1** | 🔵 **Azure Event Hubs in Bicep (§18.8)** | 🟡 Med | KEDA scaling broken without Event Hubs |
| **P1** | 🔵 **Azure feature flags validation (§18.1)** | 🟢 Small | All flags must be tested in Azure mode |
| **P1** | K8s manifests for all agents (§4.2) | 🟡 Med | Cannot deploy to AKS without them |
| **P1** | Database migrations framework (§6.2) | 🟢 Small | No schema versioning |
| **P1** | CI/CD cleanup (§8.2) — remove `ci.yml`, validate matrix | 🟢 Small | Duplicate pipelines cause confusion |
| **P1** | Frontend polish (§11.2) — reports, admin, real-time updates | 🟡 Med | Dashboard barely functional |
| **P2** | 🔵 **Azure Private Link / VNet (§18.9)** | 🔴 Large | Security requirement from README |
| **P2** | Integration & E2E tests (§2.2) — multi-drug, negative paths | 🟡 Med | Single E2E scenario insufficient |
| **P2** | Observability (§10.2) — dashboards, alerts, deep health | 🟡 Med | Cannot operate blind in prod |
| **P2** | Missing KEDA scalers (§4.3) + K8s extras (§4.4) | 🟢 Small | Scaling won't work for 3 pillars |
| **P2** | Bicep IaC gaps (§5.2–5.3) — remaining resources | 🟡 Med | Production IaC incomplete |
| **P3** | MCP Server hardening (§12.2) — auth, error tests, SSE | 🟢 Small | Nice-to-have for Claude integration |
| **P3** | Performance optimization (§15.2) — connection pools, LLM tokens, caching | 🟡 Med | Optimization without metrics is premature |
| **P3** | Resilience (§14.2) — idempotency, DLQ processing, timeouts | 🟡 Med | Edge cases in production |
| **P4** | ML/DPO pipeline (§13.2) — tests, Celery wiring, evaluation | 🔴 Large | Cost optimization — not blocking launch |
| **P4** | Documentation (§16.2) — OpenAPI, ADRs, deployment guide | 🟢 Small | Operational readiness |
| **P4** | Performance & load testing (§3) | 🟡 Med | Post-launch optimization |
| **P4** | Docker optimization (§17.2) — image sizes, non-root, security | 🟢 Small | Polish |

---

## File-Level Inventory

### Source Code (103 files across 5 modules)

```
src/
├── agents/                     # 41 files
│   ├── planner/                # 5 files (decomposer, publisher, main, Dockerfile, __init__)
│   ├── supervisor/             # 4 files (validator, conflict_resolver, main, __init__)
│   ├── executor/               # 5 files (report_generator, chart_generator, pdf_engine, main, __init__)
│   ├── retrievers/             # 22 files
│   │   ├── base_retriever.py   # 533 lines — abstract lifecycle
│   │   ├── legal/              # 3 files (tools.py, main.py, __init__.py)
│   │   ├── clinical/           # 3 files
│   │   ├── commercial/         # 3 files
│   │   ├── social/             # 3 files
│   │   ├── knowledge/          # 4 files
│   │   └── news/               # 3 files
│   ├── quality_evaluator/      # 2 files
│   └── prompt_enhancer/        # 2 files
├── shared/                     # 48 files
│   ├── config.py               # 362 lines — 12 service configs
│   ├── infra/                  # 21 files (cosmos, graph, websocket, NER, SB, telemetry, etc.)
│   ├── a2a/                    # 8 files (agent_mesh, protocol, registry, capability_contract, etc.)
│   ├── rag/                    # 4 files (chunker, ingestion, retriever, __init__)
│   ├── spar/                   # 2 files (reflect, __init__)
│   ├── memory/                 # 3 files (short_term, long_term, __init__)
│   ├── models/                 # 3 files (schemas, enums, __init__)
│   └── tasks/                  # 5 files (analytics, celery_ingestion, pdf, rag, __init__)
├── frontend/                   # 9+ files (Next.js 15)
├── mcp/                        # 2 files (mcp_server.py, __init__.py)
└── ml/                         # 3 files (data_collector.py, dpo_training.py, __init__.py)
```

### Tests (19 files)

```
tests/
├── __init__.py
├── test_models.py              # Pydantic schemas & enums
├── test_e2e_keytruda.py        # E2E flow
├── test_integration.py         # Cross-service integration
└── unit/                       # 15 files
    ├── test_agent_mesh.py
    ├── test_blob_client.py
    ├── test_clinical_retriever.py
    ├── test_commercial_retriever.py
    ├── test_graph_client.py
    ├── test_keyvault_resolver.py
    ├── test_legal_retriever.py
    ├── test_llm_cache.py
    ├── test_message_broker.py
    ├── test_ner_service.py
    ├── test_rag_pipeline.py
    ├── test_redis_client.py
    ├── test_social_retriever.py
    └── test_websocket.py
```

### Infrastructure (14 files)

```
infra/
├── main.bicep                  # Legacy (smaller)
├── bicep/main.bicep            # Production (277 lines, 12+ resources)
├── k8s/
│   ├── deployment.yaml         # Legacy monolith deployment
│   ├── keda-scalers.yaml       # Legacy scaler config
│   ├── secrets.template.yaml   # Secrets template
│   ├── base/                   # Kustomize base
│   │   ├── planner-deployment.yaml
│   │   ├── supervisor-deployment.yaml
│   │   ├── executor-deployment.yaml
│   │   ├── namespace.yaml
│   │   ├── configmap.yaml
│   │   └── kustomization.yaml
│   └── keda/
│       └── scaled-objects.yaml # 4 ScaledObjects (130 lines)
├── db/init/                    # PostgreSQL init script
└── migrations/001_initial.py   # Initial migration (4,824 bytes)
```
update