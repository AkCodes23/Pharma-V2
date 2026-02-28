# Pharma Agentic AI — Claude Code Instructions

## Project Overview

Distributed, multi-agent pharmaceutical intelligence platform. Converts natural-language drug queries (e.g., "Should I launch generic Keytruda in India?") into citation-grounded, hallucination-free GO/NO-GO decision reports.

**Architecture**: Planner → Service Bus/Kafka → 5 Retriever Agents (Legal, Clinical, Commercial, Social, Knowledge/RAG) → Quality Evaluator + Prompt Enhancer → Supervisor (Grounding Validator) → Executor (Report + PDF + Charts) → SPAR Reflection

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12, FastAPI, Pydantic v2, Pydantic-Settings |
| **LLM** | Azure OpenAI GPT-4o (Strict JSON Mode) |
| **Messaging** | Azure Service Bus (prod), Kafka (dev via docker-compose) |
| **Session Store** | Azure Cosmos DB (source of truth) |
| **Graph** | Neo4j (dev), Azure Cosmos Gremlin (prod) |
| **NER** | Azure AI Language Text Analytics + regex fallback |
| **Real-time** | Azure Web PubSub (prod), local WebSocket (dev) |
| **Analytics DB** | PostgreSQL 16 (dual-write from Cosmos) |
| **Cache** | Redis 7 (session cache, rate limiter, circuit breaker) |
| **Task Queue** | Celery 5 (Redis broker, Postgres backend) |
| **RAG** | ChromaDB (dev), Azure AI Search (prod) |
| **IaC** | Azure Bicep (12+ resources) |
| **Frontend** | Next.js 15, React 19, TypeScript |
| **Observability** | OpenTelemetry + structlog + Azure Monitor |
| **ML** | DPO training (HuggingFace TRL / Azure fine-tune) |
| **PDF** | WeasyPrint, Matplotlib, Plotly |

## Directory Structure

```
src/
├── agents/
│   ├── planner/          # FastAPI :8000 — query decomposition + task publishing
│   │   ├── main.py       # Endpoints: POST /analyze, GET /sessions/{id}
│   │   ├── decomposer.py # IntentDecomposer — LLM strict JSON task graph
│   │   └── publisher.py  # TaskPublisher — Service Bus / Kafka dispatch
│   ├── retrievers/
│   │   ├── base_retriever.py  # ABC: circuit breaker, timeouts, retry, DLQ
│   │   ├── legal/        # Patent search (USPTO Orange Book, IPO)
│   │   ├── clinical/     # Clinical trials (ClinicalTrials.gov)
│   │   ├── commercial/   # Market data (IQVIA proxies)
│   │   ├── social/       # Adverse events (FDA FAERS), sentiment
│   │   └── knowledge/    # Internal docs RAG (rag_engine.py)
│   ├── supervisor/
│   │   ├── main.py       # Cosmos DB Change Feed consumer
│   │   └── validator.py  # GroundingValidator — rule-based + LLM-as-judge
│   ├── executor/
│   │   ├── main.py       # Report synthesis, chart gen, PDF dispatch
│   │   ├── report_generator.py  # Context-constrained report generation
│   │   ├── pdf_engine.py        # WeasyPrint rendering + Blob upload
│   │   └── chart_generator.py   # Matplotlib/Plotly charts
│   ├── quality_evaluator/    # A2A: LLM quality scoring (accuracy/citation/relevance)
│   └── prompt_enhancer/      # A2A: Prompt refinement on quality failure
├── shared/
│   ├── config.py         # Pydantic Settings (12 service configs: Azure, Redis, Cosmos, Gremlin, NER, PubSub, etc.)
│   ├── infra/
│   │   ├── cosmos_client.py     # ETag optimistic concurrency
│   │   ├── graph_client.py      # Dual: Neo4j (Cypher) / Cosmos Gremlin — feature-flagged
│   │   ├── ner_service.py       # Azure AI Language NER + regex fallback
│   │   ├── websocket.py         # Local ConnectionManager + Azure Web PubSub
│   │   ├── servicebus_client.py # Cached senders, batch publish, DLQ
│   │   ├── redis_client.py      # Cache, dedup, rate limit, circuit breaker
│   │   ├── postgres_client.py   # Async analytics dual-write, memory
│   │   ├── kafka_client.py      # Exactly-once producer, manual-commit consumer
│   │   ├── message_broker.py    # KafkaBroker (dev) ↔ ServiceBusBroker (prod)
│   │   ├── celery_app.py        # 3 queues + Beat schedule
│   │   ├── audit.py             # 21 CFR Part 11 immutable audit trail
│   │   ├── telemetry.py         # OpenTelemetry + custom metrics
│   │   └── websocket.py         # Real-time session updates
│   ├── models/
│   │   ├── schemas.py    # Pydantic: Session, TaskNode, AgentResult, Citation
│   │   └── enums.py      # PillarType, SessionStatus, TaskStatus, etc.
│   ├── a2a/              # Agent-to-Agent protocol
│   │   ├── agent_card.py # AgentCard capability declaration
│   │   ├── protocol.py   # Delegate/Report/Escalate messages
│   │   └── registry.py   # Dual-backed (Redis + Postgres) discovery
│   ├── spar/
│   │   └── reflect.py    # SPAR Reflection: citation/timeout/decision/coverage checks
│   ├── memory/
│   │   ├── short_term.py # Redis conversation context (20 msg cap)
│   │   └── long_term.py  # Postgres user preferences + decision history
│   └── tasks/            # Celery tasks
│       ├── pdf_task.py
│       ├── rag_task.py
│       └── analytics_task.py
```

## Key Patterns & Conventions

### Code Style
- **Python 3.12+** with `from __future__ import annotations`
- **Ruff** linter: `ruff check src/ tests/` (rules: E, F, I, N, W, UP, B, SIM, RUF)
- **mypy** strict: `mypy src/ --ignore-missing-imports`
- **Line length**: 120 characters
- **Docstrings**: Every module, class, and public method

### Architecture Rules
1. **Every module** has a docstring block with: Service, Responsibility, Upstream, Downstream, Data ownership, Failure mode
2. **No shared mutable state** across services — use Redis or message broker
3. **Cosmos DB is source of truth** for session lifecycle. Redis = ephemeral cache, Postgres = analytics
4. **Audit trail is compliance-critical** (21 CFR Part 11). Never swallow audit write failures silently
5. **Circuit breaker pattern** in `base_retriever.py` — fail-fast on external API outages
6. **ETag optimistic concurrency** in `cosmos_client.py` — prevents race conditions on task status updates
7. **Context-Constrained Decoding**: LLMs receive ONLY provided context. No parametric memory in claims

### Environment Switching
- `APP_ENV=development` → Kafka, ChromaDB, local Docker stack
- `APP_ENV=production` → Service Bus, Azure AI Search, Cosmos DB, Azure Redis Cache

### Running Locally
```bash
cp .env.example .env  # Fill in Azure OpenAI credentials
docker compose up -d --build
# Swagger: http://localhost:8000/docs
# Kafka UI: http://localhost:8080
# Frontend: http://localhost:3000
```

### Running Tests
```bash
pytest tests/ -v --cov=src --cov-report=term-missing
python -m mypy src/ --ignore-missing-imports
python -m ruff check src/ tests/
```

### Adding a New Retriever Agent
1. Create `src/agents/retrievers/<pillar>/` with `__init__.py`, `main.py`, `tools.py`
2. Subclass `BaseRetriever` and implement `execute_tools(task) → (findings, citations)`
3. Add Kafka topic in `docker-compose.yml` → `kafka-init` service
4. Add Service Bus topic in `infra/main.bicep`
5. Register AgentCard in the A2A registry

### Adding a New Celery Task
1. Create task in `src/shared/tasks/<name>_task.py`
2. Decorate with `@app.task(name="src.shared.tasks.<name>_task.<func>", queue="pharma.<queue>")`
3. Add queue routing in `celery_app.py` → `task_routes`
4. If periodic, add to `beat_schedule`

## Critical Files (Review Before Changing)
- `config.py` — All services depend on this (12 config classes). Breaking it breaks everything
- `base_retriever.py` — Circuit breaker + retry logic shared by 5 agents
- `cosmos_client.py` — ETag concurrency. Incorrect changes cause race conditions
- `graph_client.py` — Dual Neo4j/Gremlin backend. Test both paths before changing
- `ner_service.py` — Azure NER + regex fallback. Category mapping affects entity extraction
- `websocket.py` — Local/PubSub switch. Protocol compatibility matters
- `servicebus_client.py` — AMQP connection caching. Pool exhaustion = deadlock
- `docker-compose.yml` — Service dependency graph. Wrong `depends_on` = startup failures
