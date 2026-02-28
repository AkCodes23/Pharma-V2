# Pharma Agentic AI — Pending Work (E2E)

> **Last Updated**: 2026-02-28  
> Comprehensive audit of all pending work across every layer of the platform.

---

## Summary

| Category | Pending Items | Blocking Production? |
|----------|:---:|:---:|
| API Integrations (Mock → Real) | 5 | ✅ Yes |
| Azure Migration (Phase 3–4) | 3 | ⚠️ Partial |
| Frontend (Mock Data → Live API) | 2 | ✅ Yes |
| Testing (Missing Coverage) | 8 | ✅ Yes |
| Infrastructure / IaC | 5 | ⚠️ Partial |
| CI/CD Pipeline | 4 | ⚠️ Partial |
| Knowledge Graph (NER) | 1 | ⚠️ Partial |
| ML Pipeline (DPO Fine-Tuning) | 2 | ❌ No |
| MCP Server | 2 | ❌ No |
| Documentation | 3 | ❌ No |

---

## 1. API Integrations — Mock → Real

These retriever tools currently return **hardcoded mock data** and need real API integration.

### 1.1 Legal Retriever — Indian Patent Office (IPO)
- **File**: `src/agents/retrievers/legal/tools.py` (line ~166–215)
- **Current**: `regional_patent_search()` returns hardcoded `mock_data` list
- **Needed**: Real IPO API integration (or web scraper + proxy) with rate limiting
- **Blocker**: IPO has no public REST API — may require scraping or a third-party data provider

### 1.2 Clinical Retriever — CDSCO (India)
- **File**: `src/agents/retrievers/clinical/tools.py` (line ~133–165)
- **Current**: `cdsco_drug_search()` returns hardcoded mock records
- **Needed**: Real CDSCO integration (API or scraper)
- **Blocker**: CDSCO has no public REST API — same scraping challenge as IPO

### 1.3 Commercial Retriever — All Tools
- **File**: `src/agents/retrievers/commercial/tools.py` (entire file)
- **Current**: `market_size_estimation()` and `revenue_forecast()` return static mock data
- **Needed**: Integration with IQVIA, GlobalData, or financial APIs (Alpha Vantage, Bloomberg)
- **Blocker**: Commercial data APIs are expensive and require licensing

### 1.4 Knowledge Retriever — Internal Document Search
- **File**: `src/agents/retrievers/knowledge/tools.py` (line ~35–74)
- **Current**: `internal_doc_search()` returns mock document results
- **Needed**: Wire to the real RAG pipeline (`src/shared/rag/rag_retriever.py` + Azure AI Search)
- **Blocker**: Requires embedding index populated with real internal documents

### 1.5 Social Retriever — Sentiment & Social Media
- **File**: `src/agents/retrievers/social/tools.py`
- **Current**: FDA FAERS integration is real; `sentiment_analysis` and `social_media_monitoring` capabilities appear limited
- **Needed**: Full sentiment pipeline (Twitter/X healthcare API, PubMed comments, Reddit medical subs)
- **Blocker**: Social API access and NLP sentiment model selection

---

## 2. Azure Migration — Remaining Phases (3–4)

Phase 1–2 (PostgreSQL, Redis, Telemetry, Event Hubs, KEDA) are **completed**. The following 3 areas remain:

### 2.1 Azure AI Language — Named Entity Recognition (NER)
- **File**: `src/shared/infra/graph_client.py` → `extract_and_store_entities()` (line ~218–236)
- **Current**: Regex heuristics for drug/company/indication extraction — fragile, misses variants
- **Needed**: New `src/shared/infra/ner_service.py` using Azure AI Language Text Analytics
- **Scope**: Custom BioNER model training (Drug, Company, Indication, Patent, MOA entity types)

### 2.2 Azure Web PubSub — Real-Time WebSocket
- **File**: `src/shared/infra/websocket.py`
- **Current**: In-process `ConnectionManager` + Redis Pub/Sub fan-out — state lost on restart
- **Needed**: Rewrite to use Azure Web PubSub SDK, clients connect directly to PubSub endpoint
- **Scope**: Eliminate in-memory connection state, add replay buffer to Azure Storage

### 2.3 Cosmos DB Gremlin API — Replace Neo4j
- **File**: `src/shared/infra/graph_client.py`
- **Current**: Neo4j driver with Cypher queries
- **Needed**: Migrate to `gremlinpython`, rewrite all Cypher → Gremlin traversals
- **Scope**: Remove `neo4j` from Docker Compose, remove `Neo4jConfig` from `config.py`

---

## 3. Frontend — Mock Data → Live API

### 3.1 Reports Page
- **File**: `src/frontend/src/app/reports/page.tsx` (line ~17–52)
- **Current**: `MOCK_REPORTS` hardcoded array, no API calls
- **Needed**: Fetch from `GET /sessions?status=COMPLETED` and link to actual PDF reports

### 3.2 Admin / Audit Page
- **File**: `src/frontend/src/app/admin/page.tsx` (line ~24–61)
- **Current**: `MOCK_AUDIT_ENTRIES` and `MOCK_HEALTH` hardcoded data
- **Needed**: Fetch from audit trail API and system health endpoints

---

## 4. Testing — Missing Coverage

### Existing Tests
| Test File | Covers |
|-----------|--------|
| `tests/test_models.py` | Pydantic schemas & enums |
| `tests/test_e2e_keytruda.py` | E2E flow (single scenario) |
| `tests/test_integration.py` | Integration tests |
| `tests/unit/test_agent_mesh.py` | A2A agent mesh |
| `tests/unit/test_llm_cache.py` | LLM response cache |
| `tests/unit/test_message_broker.py` | Kafka/SB broker abstraction |
| `tests/unit/test_rag_pipeline.py` | RAG chunking + retrieval |
| `tests/unit/test_redis_client.py` | Redis client operations |

### Missing Tests (Need Creation)
- [ ] **Planner Agent** — `decomposer.py` intent parsing, `publisher.py` task routing
- [ ] **Supervisor Agent** — `validator.py` grounding validation, `conflict_resolver.py` conflict detection
- [ ] **Executor Agent** — `report_generator.py` synthesis, `chart_generator.py` chart output, `pdf_engine.py` rendering
- [ ] **Quality Evaluator** — Scoring dimensions, pass/fail threshold logic
- [ ] **Prompt Enhancer** — Enhancement strategies, fallback behavior
- [ ] **Individual Retrievers** — Each retriever's `execute_tools()` with mocked API responses
- [ ] **SPAR Reflection** — `reflect.py` check logic, scoring
- [ ] **MCP Server** — Tool input validation, session lifecycle through MCP

---

## 5. Infrastructure / IaC

### 5.1 Missing K8s Deployment Manifests
- **Existing**: `planner-deployment.yaml`, `supervisor-deployment.yaml`, `executor-deployment.yaml`
- **Missing**:
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

### 5.2 Missing KEDA ScaledObjects
- **Existing**: Legal, Clinical, News retriever scalers; Celery worker scaler
- **Missing**:
  - [ ] `retriever-commercial-scaler` (ScaledObject for `pharma.tasks.commercial`)
  - [ ] `retriever-social-scaler` (ScaledObject for `pharma.tasks.social`)
  - [ ] `retriever-knowledge-scaler` (ScaledObject for `pharma.tasks.knowledge`)

### 5.3 Bicep IaC Gaps
- **Current `main.bicep`**: Cosmos DB, Service Bus (5 topics), Key Vault, Blob Storage, Container Apps Env, Log Analytics
- **Missing**:
  - [ ] Azure Event Hubs namespace + 6 event hubs (to replace Kafka)
  - [ ] Azure Cache for Redis resource
  - [ ] Azure DB for PostgreSQL — Flexible Server
  - [ ] Azure AI Search resource (for production RAG)
  - [ ] Azure OpenAI resource
  - [ ] Azure Web PubSub resource
  - [ ] Azure AI Language resource (for NER)
  - [ ] Container App definitions for each agent service
  - [ ] Service Bus topic for `news-tasks` (missing, only 5 of 6 pillars defined)

### 5.4 Database Migrations
- **File**: `infra/db/init/` — only 1 init script exists
- **Missing**:
  - [ ] PostgreSQL migration framework (Alembic or Flyway)
  - [ ] Schema versioning for `reflection_log`, `agent_registry`, `audit`, `memory` tables
  - [ ] Cosmos DB container definitions for new collections (if any)

### 5.5 Secrets Management
- Key Vault is declared in Bicep but:
  - [ ] No secret references from Container Apps to Key Vault
  - [ ] No Managed Identity assignments for agent services
  - [ ] `.env` contains raw credentials — needs migration to Key Vault references

---

## 6. CI/CD Pipeline

### Current (`ci.yml`)
- ✅ Lint (Ruff)
- ✅ Type check (mypy)
- ✅ Python unit tests with coverage
- ✅ Frontend lint + type check
- ✅ Docker image build (planner only)

### Missing
- [ ] **Docker builds for all services** — CI matrix only builds `planner`; need executor, supervisor, retrievers (×6), quality evaluator, prompt enhancer, celery, MCP, frontend
- [ ] **CD pipeline** — No deployment workflow (Azure Container Apps, AKS, or ACR push)
- [ ] **Integration test stage** — No stage runs `test_integration.py` with Docker Compose services
- [ ] **Security scanning** — No SAST (Bandit), dependency audit (`pip-audit`), or container scanning (Trivy)

---

## 7. Knowledge Graph (NER) Placeholder

- **File**: `src/shared/infra/graph_client.py` → `extract_and_store_entities()` (line ~218)
- **Current**: Comment says *"Placeholder — entity extraction requires NER model"*
- **Status**: Simple regex heuristics — not production-grade
- **Needed**: Replace with Azure AI Language NER (see §2.1) or SciSpacy/BioBERT model

---

## 8. ML Pipeline (DPO Fine-Tuning)

### 8.1 Data Collector — Untested
- **File**: `src/ml/data_collector.py`
- **Current**: Implemented but never tested (no test file for ML module)
- **Needed**: Unit tests for `DPODataCollector`, mock `reflection_log` queries

### 8.2 Training Pipeline — Not Implemented
- **Current**: Data collection → JSONL export exists
- **Missing**:
  - [ ] Training script using `trl` DPO trainer
  - [ ] Model evaluation and benchmarking pipeline
  - [ ] Model deployment (Azure ML or local SLM inference)
  - [ ] Celery Beat task for weekly data extraction (referenced in docstring but not wired)
  - [ ] Integration with Quality Evaluator for A/B testing (GPT-4o vs local SLM)

---

## 9. MCP Server

### 9.1 Tool Coverage
- **File**: `src/mcp/mcp_server.py` (708 lines, 8+ tools declared)
- **Current**: Tools call Planner API via HTTP — functional but untested end-to-end
- **Missing**:
  - [ ] Error handling tests for each tool
  - [ ] Rate limiting per MCP client
  - [ ] Authentication/authorization for MCP tool calls

### 9.2 Resource Subscriptions
- **File**: `src/mcp/mcp_server.py`
- **Current**: Static resource reads declared (`pharma://sessions/{id}`, `pharma://agents/active`)
- **Missing**:
  - [ ] Real-time resource subscription (SSE) for session status updates
  - [ ] Integration tests validating MCP protocol compliance

---

## 10. Documentation

- [ ] **API Documentation** — No OpenAPI schema published for Supervisor (`:8001`) or Executor (`:8002`) endpoints
- [ ] **Architecture Decision Records (ADRs)** — No ADR documents for key decisions (e.g., why Cosmos DB over DynamoDB, why Kafka over RabbitMQ)
- [ ] **Runbook** — No operational runbook for incident response, DLQ processing, or manual circuit breaker reset

---

## Priority Execution Order

| Phase | Items | Effort | Why First? |
|:---:|--------|:---:|------------|
| **P0** | Mock API replacements (§1.4 Knowledge, §1.3 Commercial minimum viable) | 🟡 Med | Core pipeline returns fake data |
| **P1** | Frontend live API wiring (§3) | 🟢 Small | Dashboard is unusable without real data |
| **P1** | Missing unit tests for agents (§4) | 🟡 Med | No confidence in code correctness |
| **P2** | K8s manifests + missing KEDA scalers (§5.1, §5.2) | 🟡 Med | Cannot deploy to AKS without them |
| **P2** | CI/CD — Docker builds for all services + CD (§6) | 🟡 Med | Blocked from automated deployments |
| **P2** | Azure migration Phase 3–4 (§2) | 🔴 Large | NER, Web PubSub, Gremlin — reduces ops burden |
| **P3** | Bicep IaC — remaining Azure resources (§5.3) | 🟡 Med | Production IaC incomplete |
| **P3** | Security scanning in CI (§6) | 🟢 Small | Compliance gap |
| **P4** | ML/DPO pipeline (§8) | 🔴 Large | Cost optimization — not blocking launch |
| **P4** | MCP Server hardening (§9) | 🟢 Small | Nice-to-have for Claude integration |
| **P4** | Documentation (§10) | 🟢 Small | Operational readiness |
