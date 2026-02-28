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
├── infra/
│   ├── bicep/main.bicep            # 12+ Azure resources (OpenAI, Cosmos, SB, etc.)
│   ├── k8s/
│   │   ├── deployment.yaml         # AKS manifests (Planner, Supervisor, Executor, Frontend)
│   │   ├── keda-scalers.yaml       # Service Bus queue-based auto-scaling (1→10 replicas)
│   │   └── secrets.template.yaml   # Secrets template (never committed)
│   └── migrations/
│       └── 001_initial.py          # PostgreSQL schema (sessions, audit, metrics, DPO)
├── src/
│   ├── agents/
│   │   ├── planner/                # FastAPI :8000 — query decomposition + task publishing
│   │   ├── retrievers/
│   │   │   ├── base_retriever.py   # Abstract lifecycle (consume → execute → persist)
│   │   │   ├── legal/              # USPTO Orange Book + IPO web scraper + fallback
│   │   │   ├── clinical/           # ClinicalTrials.gov v2 + FDA approvals + CDSCO scraper
│   │   │   ├── commercial/         # SEC EDGAR + Yahoo Finance + TAM estimation
│   │   │   ├── social/             # FDA FAERS + PubMed E-utilities + composite sentiment
│   │   │   └── knowledge/          # Azure AI Search RAG pipeline (hybrid search)
│   │   ├── supervisor/             # Grounding Validator (rule + conflict + LLM judge)
│   │   └── executor/               # Report synthesis + PDF + charts
│   ├── frontend/                   # Next.js 15 dark dashboard (live API, no mocks)
│   ├── ml/
│   │   └── dpo_training.py         # DPO pipeline (data collector + local/Azure trainer)
│   └── shared/
│       ├── infra/
│       │   ├── cosmos_client.py     # Cosmos DB operations + Change Feed
│       │   ├── graph_client.py      # Dual-backend: Neo4j (dev) + Cosmos Gremlin (prod)
│       │   ├── ner_service.py       # Azure AI Language NER + regex fallback
│       │   ├── websocket.py         # Local ConnectionManager + Azure Web PubSub
│       │   ├── servicebus_client.py # Topic-based pub/sub with DLQ
│       │   └── telemetry.py         # OpenTelemetry + structlog + Azure Monitor
│       └── config.py               # Unified Pydantic Settings (12 service configs)
├── tests/
│   ├── unit/                        # 12 test files, ~80+ test cases
│   ├── test_integration.py          # Cross-service integration tests
│   └── test_e2e_keytruda.py         # End-to-end scenario test
├── .github/workflows/ci-cd.yaml     # 8-job CI/CD (lint, test, security, build, deploy)
├── Dockerfile                       # Multi-stage (planner | supervisor | executor | worker)
└── pyproject.toml
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
| Compute | AKS (Kubernetes) + KEDA auto-scaling |
| LLM | Azure OpenAI GPT-4o |
| State | Azure Cosmos DB (NoSQL + Gremlin) |
| Messaging | Azure Service Bus (6 topics) |
| Graph | Neo4j (dev) / Cosmos Gremlin (prod) |
| NER | Azure AI Language + regex fallback |
| Real-time | Azure Web PubSub + local WebSocket |
| RAG | Azure AI Search (hybrid + semantic) |
| Frontend | Next.js 15, React 19, TypeScript |
| ML | DPO training (TRL local / Azure fine-tune) |
| Observability | OpenTelemetry → Azure Monitor |
| IaC | Azure Bicep (12+ resources) |
| CI/CD | GitHub Actions (8-job pipeline) |
| Security | Bandit + Safety scan, secrets in Key Vault |

---

## 📄 License

Proprietary. All rights reserved.
