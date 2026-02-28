# Pharma Agentic AI — Agent Registry

> Complete reference for every agent in the distributed swarm.
> Each entry defines the agent's role, capabilities, data flow, and failure behavior.

---

## System Architecture

```
  User Query
      ↓
  ┌──────────┐     ┌────────────────────────────────┐
  │ Planner  │────→│  Message Broker (Kafka / SB)    │
  │ :8000    │     └──────┬──┬──┬──┬──┬──────────────┘
  └──────────┘            │  │  │  │  │
      ↕ Redis             ↓  ↓  ↓  ↓  ↓
  ┌──────────┐     Legal Clin Comm Soc Know
  │ ShortTerm│     Retr  Retr Retr Retr Retr+RAG
  │ Memory   │            │  │  │  │  │
  └──────────┘            ↓  ↓  ↓  ↓  ↓
                   ┌─────────────────────────┐
                   │   Quality Evaluator     │ ← LLM scoring
                   └──────┬──────────────────┘
                          │ pass / fail
                   ┌──────↓──────┐
            fail → │Prompt Enhancer│ → retry
                   └─────────────┘
                          │ pass
                   ┌──────↓──────────────┐
                   │  Supervisor :8001    │ ← Grounding + Conflicts
                   │  (Cosmos Change Feed)│
                   └──────┬──────────────┘
                          ↓
                   ┌──────────────────┐
                   │  Executor :8002  │ → Reports, PDF, Charts
                   │  + SPAR Reflect  │
                   └──────┬───────────┘
                          ↓
                   ┌──────────────────┐
                   │  Celery Workers  │ → PDF gen, RAG index, analytics
                   └──────────────────┘
```

---

## 1. Planner Agent

| Property | Value |
|----------|-------|
| **Type** | `PLANNER` |
| **Port** | `8000` |
| **Entry** | `src/agents/planner/main.py` |
| **Responsibility** | Decompose natural-language queries into a task graph |

### Capabilities
- Accepts user queries via `POST /analyze`
- Uses `IntentDecomposer` (GPT-4o Strict JSON) to extract structured `QueryParameters`
- Generates one `TaskNode` per relevant pillar (up to 5)
- Publishes tasks via `TaskPublisher` → Service Bus (prod) / Kafka (dev)
- Creates session in Cosmos DB with `PLANNING` → `RETRIEVING` status transition
- Integrates `ShortTermMemory` for multi-turn conversations
- Session polling via `GET /sessions/{id}` (Redis-cached)
- WebSocket real-time updates: `ws://localhost:8000/ws/sessions/{id}`

### Input/Output
- **Input**: `{ "query": "string", "user_id": "string" }`
- **Output**: `{ "session_id": "uuid", "status": "PLANNING", "tasks": [...] }`

### Failure Behavior
- Missing query → `422 Validation Error`
- LLM timeout → Retry with backoff (3 attempts)
- Ambiguous query → Returns clarification request (no tasks published)

---

## 2. Legal Retriever Agent

| Property | Value |
|----------|-------|
| **Type** | `LEGAL_RETRIEVER` |
| **Pillar** | `LEGAL` |
| **Entry** | `src/agents/retrievers/legal/main.py` |
| **Responsibility** | Patent and exclusivity data retrieval |

### Capabilities
- `patent_search` — FDA Orange Book search (openFDA API)
- `exclusivity_lookup` — Patent exclusivity period check
- `regional_patent_search` — Indian Patent Office (if market = India)
- `blocking_patent_detection` — Identifies active blocking patents
- Computes `earliest_generic_entry` date from all blocking patent expiry dates

### Data Sources
| Source | API | Citation |
|--------|-----|----------|
| FDA Orange Book | openFDA | `FDA Orange Book — Accessed {date}` |
| Patent Exclusivity | openFDA | `FDA Patent Exclusivity — Accessed {date}` |
| Indian Patent Office | IPO API | `Indian Patent Office — Accessed {date}` |

### Failure Behavior
- API failure → Circuit breaker (5 failures → OPEN for 60s)
- Timeout → 120s hard limit per task
- DLQ → After 3 retries, message dead-lettered

---

## 3. Clinical Retriever Agent

| Property | Value |
|----------|-------|
| **Type** | `CLINICAL_RETRIEVER` |
| **Pillar** | `CLINICAL` |
| **Entry** | `src/agents/retrievers/clinical/main.py` |
| **Responsibility** | Clinical trial landscape analysis |

### Capabilities
- `clinical_trial_search` — ClinicalTrials.gov active/completed trials
- `competitive_saturation_analysis` — Count active competitor trials
- `fda_approval_check` — FDA approval status verification
- `bioequivalence_check` — BE study requirements analysis

### Data Sources
| Source | API | Citation |
|--------|-----|----------|
| ClinicalTrials.gov | CT.gov v2 API | `ClinicalTrials.gov — Accessed {date}` |
| FDA Drug Approvals | openFDA | `FDA Drug Approvals — Accessed {date}` |

---

## 4. Commercial Retriever Agent

| Property | Value |
|----------|-------|
| **Type** | `COMMERCIAL_RETRIEVER` |
| **Pillar** | `COMMERCIAL` |
| **Entry** | `src/agents/retrievers/commercial/main.py` |
| **Responsibility** | Market intelligence and financial analysis |

### Capabilities
- `market_size_estimation` — TAM/SAM/SOM analysis
- `competitor_landscape` — Generic competitor count and market share
- `pricing_analysis` — Price benchmarking across markets
- `market_attractiveness_scoring` — HIGH/MEDIUM/LOW classification

---

## 5. Social Retriever Agent

| Property | Value |
|----------|-------|
| **Type** | `SOCIAL_RETRIEVER` |
| **Pillar** | `SOCIAL` |
| **Entry** | `src/agents/retrievers/social/main.py` |
| **Responsibility** | Adverse event monitoring and sentiment analysis |

### Capabilities
- `adverse_event_search` — FDA FAERS database
- `regulatory_risk_assessment` — Safety signal severity
- `sentiment_analysis` — Medical community perception
- `social_media_monitoring` — Healthcare professional discussions

### Data Sources
| Source | API | Citation |
|--------|-----|----------|
| FDA FAERS | openFDA Adverse Events | `FDA FAERS — Accessed {date}` |

---

## 6. Knowledge Retriever Agent (RAG)

| Property | Value |
|----------|-------|
| **Type** | `KNOWLEDGE_RETRIEVER` |
| **Pillar** | `KNOWLEDGE` |
| **Entry** | `src/agents/retrievers/knowledge/main.py` |
| **Responsibility** | Internal document search via RAG pipeline |

### RAG Pipeline (`rag_engine.py`)
1. **Ingest**: PDF/CSV/HTML → text extraction (pypdf)
2. **Chunk**: 512 tokens, 50 overlap, section-aware splitting
3. **Embed**: Azure OpenAI `text-embedding-ada-002` (batched 16x)
4. **Store**: ChromaDB (dev) / Azure AI Search (prod)
5. **Search**: Hybrid (BM25 keyword + cosine vector similarity)
6. **Cite**: Each chunk carries source doc metadata → Citation Registry

### Capabilities
- `internal_doc_search` — Vector search across pharma internal docs
- `regulatory_guidance_lookup` — Find relevant regulatory guidelines
- `historical_analysis_lookup` — Prior drug analysis retrieval

---

## 7. Quality Evaluator Agent (A2A)

| Property | Value |
|----------|-------|
| **Type** | `QUALITY_EVALUATOR` |
| **Entry** | `src/agents/quality_evaluator/main.py` |
| **Responsibility** | Pre-validation quality scoring of agent results |

### Scoring Dimensions
| Dimension | Weight | Description |
|-----------|--------|-------------|
| Factual Accuracy | 50% | Claims supported by citations? |
| Citation Completeness | 30% | Every data point cited? |
| Relevance | 20% | Result relevant to query? |

### Decision
- **Overall ≥ 0.6** → Pass to Supervisor
- **Overall < 0.6** → Route to Prompt Enhancer for retry
- **Evaluator failure** → Fail-open (pass result through unscored)

---

## 8. Prompt Enhancer Agent (A2A)

| Property | Value |
|----------|-------|
| **Type** | `PROMPT_ENHANCER` |
| **Entry** | `src/agents/prompt_enhancer/main.py` |
| **Responsibility** | Improve failed prompts for retry attempts |

### Strategies
| Strategy | When Used |
|----------|-----------|
| **Specificity** | Result too broad or vague |
| **Constraints** | Missing citation requirements |
| **Decompose** | Complex query → simpler sub-queries |
| **Rephrase** | Ambiguous language causing irrelevant results |

### Failure Behavior
- Enhancement failure → Use original prompt (never blocks retry)

---

## 9. Supervisor Agent

| Property | Value |
|----------|-------|
| **Type** | `SUPERVISOR` |
| **Port** | `8001` |
| **Entry** | `src/agents/supervisor/main.py` |
| **Responsibility** | Grounding validation and conflict detection |

### Validation Pipeline (`validator.py`)
1. **Rule-based citation check**: Count results with ≥ 1 citation
2. **Rule-based conflict detection**: 3 conflict patterns (Patent↔Market, Competition↔Safety, Market↔NoData)
3. **LLM-as-judge**: Semantic conflict detection via GPT-4o
4. **Decision**: `is_valid = grounding_score ≥ 0.8 AND no CRITICAL conflicts`

### Conflict Types
| Type | Pillars | Severity |
|------|---------|----------|
| `PATENT_MARKET_CONFLICT` | Legal + Commercial | CRITICAL |
| `COMPETITION_SAFETY_CONFLICT` | Clinical + Social | HIGH |
| `DATA_GAP` | Commercial + Clinical | MEDIUM |

### Failure Behavior
- LLM validation failure → Use rule-based results only (degraded but functional)
- All tasks failed → Session marked `FAILED`, audit logged

---

## 10. Executor Agent

| Property | Value |
|----------|-------|
| **Type** | `EXECUTOR` |
| **Port** | `8002` |
| **Entry** | `src/agents/executor/main.py` |
| **Responsibility** | Report synthesis, PDF generation, chart creation |

### Pipeline
1. **Synthesize**: Context-constrained report via `ReportGenerator`
2. **Charts**: Matplotlib/Plotly visualizations via `ChartGenerator`
3. **PDF**: Dispatched to Celery (`pdf_task.py`) — non-blocking
4. **Upload**: Blob Storage (report + charts)
5. **Reflect**: SPAR reflection on session quality (non-blocking)
6. **Complete**: Session status → `COMPLETED`

### Report Sections
- Executive Summary, Pillar Analyses (5), Citation Registry, GO/NO-GO Decision

---

## 11. SPAR Reflection Engine

| Property | Value |
|----------|-------|
| **Entry** | `src/shared/spar/reflect.py` |
| **Responsibility** | Post-session quality assessment and learning |

### Checks
| Check | What It Validates |
|-------|------------------|
| Citation Validity | All citations have source_name + source_url |
| Timeout Detection | No tasks stuck in FAILED/DLQ/TIMED_OUT |
| Decision Consistency | GO + low grounding → flag, NO_GO + high evidence → flag |
| Pillar Coverage | All 5 expected pillars contributed results |

### Output
- Overall score (0-1), improvement suggestions, persisted to `reflection_log` (PostgreSQL)

---

## Celery Background Workers

### Queues
| Queue | Tasks | Schedule |
|-------|-------|----------|
| `pharma.pdf` | PDF generation (WeasyPrint) | On-demand |
| `pharma.rag` | Document ingestion, re-indexing | On-demand + daily 2AM |
| `pharma.analytics` | MV refresh, stale cleanup, health check | 15m / 1h / 5m |

---

## A2A Protocol

### Message Types
| Type | Direction | Purpose |
|------|-----------|---------|
| `DISCOVER` | Broadcast | Find agents with capability |
| `DELEGATE` | Agent → Agent | Forward a sub-task |
| `REPORT` | Agent → Agent | Return result |
| `ESCALATE` | Agent → Human | Confidence below threshold |
| `HEARTBEAT` | Agent → Registry | Liveness signal (30s) |

### Registry
- **Redis**: Fast heartbeat (TTL 60s auto-expiry)
- **PostgreSQL**: Persistent metadata + capability search (`capabilities @> '["patent_search"]'`)
