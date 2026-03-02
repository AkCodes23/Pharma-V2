# Pharma Agentic AI — Developer Onboarding Guide

## Quick Start (5 minutes)

### 1. Clone & Install

```bash
git clone https://github.com/your-org/pharma-v2.git
cd pharma-v2

# Backend
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env — set at minimum:
#   AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT
#   (other services optional for local dev)
```

### 3. Run Locally

```bash
# Backend (Planner Agent)
uvicorn src.agents.planner.main:app --reload --port 8000

# Frontend
cd frontend && npm run dev
```

### 4. Run Tests

```bash
pytest tests/unit/ -v --tb=short
```

## Architecture Overview

```
User Query → Planner → Service Bus → [6 Retriever Agents] → Supervisor → Executor → PDF Report
                                        ↕                       ↕
                                    Quality Evaluator      Conflict Resolver
                                        ↕
                                    Prompt Enhancer
```

**Key modules:**

| Module | Path | Purpose |
|--------|------|---------|
| Planner | `src/agents/planner/` | Query decomposition → task graph |
| Supervisor | `src/agents/supervisor/` | Grounding validation + conflict detection |
| Executor | `src/agents/executor/` | Report generation + PDF + charts |
| Retrievers | `src/agents/retrievers/` | Pillar-specific data retrieval |
| Quality Evaluator | `src/agents/quality_evaluator/` | Pre-validation scoring |
| Prompt Enhancer | `src/agents/prompt_enhancer/` | Failed prompt improvement |
| SPAR | `src/shared/spar/` | Sense-Plan-Act-Reflect lifecycle |
| MCP Server | `src/mcp/` | LLM tool integration |
| Shared Config | `src/shared/config.py` | Pydantic settings |
| Infrastructure | `src/shared/infra/` | Cosmos, Service Bus, Redis, etc. |

## Key Patterns

### Bootstrap Sequence
Every agent calls `bootstrap_agent()` first in its lifespan to:
1. Resolve secrets from Key Vault
2. Load validated Pydantic settings
3. Initialize OpenTelemetry

### Service Bus Routing
Tasks are routed by `PillarType` to dedicated topics. See `servicebus_client.py → _topic_map`.

### Context-Constrained Decoding
The Executor uses strict prompt rules to prevent LLM hallucination. Decision logic is deterministic (not LLM-delegated).

## Development Workflow

1. Create feature branch from `main`
2. Write tests first (see `tests/unit/` examples)
3. Implement changes
4. Run `pytest tests/unit/ -v` — all tests must pass
5. Run `pip-audit` for dependency security
6. Create PR with description of changes, what could break, and rollback steps

## Useful Commands

```bash
# Run specific test file
pytest tests/unit/test_decomposer.py -v

# Check code style
ruff check src/

# Type checking
mypy src/ --ignore-missing-imports

# Security audit
pip-audit
```
