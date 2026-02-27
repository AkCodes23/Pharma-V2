# 🧬 Pharma Agentic AI — Strategic Command Center

> **Distributed Multi-Agent Pharmaceutical Intelligence Platform**
>
> Reduce Time-to-Insight from 3 weeks to under 5 minutes.
> 100% citation-grounded. Zero hallucinations. Serverless economics.

[![CI](https://github.com/your-org/pharma-agentic-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/pharma-agentic-ai/actions)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![Next.js 15](https://img.shields.io/badge/Next.js-15-black.svg)](https://nextjs.org)
[![Azure](https://img.shields.io/badge/Azure-Native-0078D4.svg)](https://azure.microsoft.com)

---

## 🎯 Problem

The pharmaceutical industry faces a **$300B patent cliff** (2025–2030). Strategic decisions like *"Should we launch a generic in India by 2027?"* require simultaneous validation across **four isolated pillars**:

| Pillar | Question | Data Source |
|--------|----------|-------------|
| ⚖️ **Legal** | Are blocking patents expired? | USPTO Orange Book, IPO |
| 🧪 **Clinical** | Is the market saturated with trials? | ClinicalTrials.gov, CDSCO |
| 📊 **Commercial** | Is the TAM expanding? | IQVIA, Financial APIs |
| 🛡️ **Social** | Are there safety signals? | FDA FAERS |

**Standard LLMs** hallucinate patent dates → **regulatory liability**.  
**Human analysts** work sequentially → **3-week cycle time**.

## 🚀 Solution

We deploy an **asynchronous Agent Swarm** — not one AI trying to know everything, but a **Planner orchestrating specialists**:

```
User Query → Planner Agent → Service Bus → Retriever Swarm (parallel) 
                                              → Cosmos DB → Supervisor → Executor → PDF Report
```

### Three Promises

1. **Precision over Prediction** — Agents use deterministic API tools, not parametric memory
2. **Systems Thinking over Single Models** — Planner-Retriever-Supervisor-Executor with KEDA scaling
3. **Intelligence that Drives Decisions** — Structured GO/NO-GO with cryptographic citation tracing

---

## 🏗 Architecture

```
pharma-agentic-ai/
├── infra/                          # Azure Bicep IaC templates
│   └── main.bicep                  # Cosmos DB, Service Bus, ACA, Key Vault
├── src/
│   ├── agents/
│   │   ├── planner/                # Intent decomposition → DAG generation
│   │   │   ├── main.py             # FastAPI entry point
│   │   │   ├── decomposer.py       # GPT-4o Strict JSON intent parsing
│   │   │   └── publisher.py        # Session creation + Service Bus routing
│   │   ├── retrievers/
│   │   │   ├── base_retriever.py   # Abstract lifecycle (consume → execute → persist)
│   │   │   ├── legal/              # USPTO Orange Book + Indian Patent Office
│   │   │   ├── clinical/           # ClinicalTrials.gov v2 + CDSCO
│   │   │   ├── commercial/         # Market TAM, revenue, CAGR analysis
│   │   │   ├── social/             # FDA FAERS adverse events + safety scoring
│   │   │   └── knowledge/          # Azure AI Search internal RAG
│   │   ├── supervisor/
│   │   │   ├── main.py             # Quality gate — validates all results
│   │   │   └── validator.py        # 3-pass: rule-based → conflict detection → LLM judge
│   │   └── executor/
│   │       ├── main.py             # Final synthesis orchestrator
│   │       ├── report_generator.py # Context-Constrained Decoding (zero hallucination)
│   │       └── chart_generator.py  # Revenue, patent timeline, safety charts
│   ├── frontend/                   # Next.js 15 premium dark dashboard
│   │   └── src/app/
│   │       ├── page.tsx            # Main dashboard with agent status grid
│   │       ├── layout.tsx          # Root layout with navigation
│   │       └── globals.css         # Dark glassmorphism design system
│   └── shared/
│       ├── models/
│       │   ├── enums.py            # PillarType, AgentType, SessionStatus, etc.
│       │   └── schemas.py          # Session, TaskNode, AgentResult, Citation, AuditEntry
│       ├── infra/
│       │   ├── cosmos_client.py    # Cosmos DB operations + Change Feed
│       │   ├── servicebus_client.py # Topic-based pub/sub with DLQ
│       │   ├── telemetry.py        # OpenTelemetry + structlog
│       │   └── audit.py            # 21 CFR Part 11 compliance trail
│       └── config.py              # Unified Pydantic Settings
├── tests/
│   └── test_models.py              # Unit tests for schemas & enums
├── .github/workflows/ci.yml        # CI pipeline
├── pyproject.toml                  # Python dependencies
└── .env.example                    # Environment template
```

---

## ⚡ Quick Start

### Prerequisites

- Python 3.12+
- Node.js 20+
- Azure subscription (for full deployment)

### 1. Clone & Install

```bash
git clone https://github.com/your-org/pharma-agentic-ai.git
cd pharma-agentic-ai

# Python backend
pip install -e ".[dev]"

# Frontend
cd src/frontend
npm install
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your Azure credentials
```

### 3. Run Backend (Planner Agent)

```bash
uvicorn src.agents.planner.main:app --reload --port 8000
```

### 4. Run Frontend

```bash
cd src/frontend
npm run dev
```

### 5. Run Tests

```bash
pytest tests/ -v --cov=src
```

---

## 🔐 Security & Compliance

| Standard | Implementation |
|----------|---------------|
| **FDA 21 CFR Part 11** | Immutable Cosmos DB audit trail, SHA-256 payload hashing |
| **EU GMP Annex 11** | Electronic signatures via Azure Entra ID MFA |
| **Network Security** | Azure Private Link, zero public endpoints |
| **Identity** | Passwordless (Managed Identities), RBAC |
| **Encryption** | AES-256 at-rest, TLS 1.3 in-transit |

---

## 💰 Cost Model

| Scale | Monthly Cost | Per Query |
|:-----:|:-----------:|:---------:|
| Idle | **$0** | — |
| 10K queries | ~$150 | $0.015 |
| 100K queries | ~$1,300 | $0.013 |

---

## 📊 Key Metrics

| Metric | Target |
|--------|--------|
| Time-to-Insight | < 5 minutes |
| Hallucination Rate | 0% |
| Citation Coverage | 100% |
| System Uptime | 99.9% |

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | Microsoft Semantic Kernel |
| Compute | Azure Container Apps + KEDA |
| LLM | Azure OpenAI GPT-4o |
| State | Azure Cosmos DB (Serverless) |
| Messaging | Azure Service Bus |
| Frontend | Next.js 15, React 19, TypeScript |
| Observability | OpenTelemetry → Azure Monitor |
| IaC | Azure Bicep |
| CI/CD | GitHub Actions |

---

## 📄 License

Proprietary. All rights reserved.
