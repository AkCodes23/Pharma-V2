# ADR-007: SPAR Lifecycle for Agent Orchestration

**Status:** Accepted  
**Date:** 2026-03-02  
**Decision Makers:** AI Engineering Team

## Context

The platform needs a structured lifecycle for multi-agent sessions that enables post-session learning, quality tracking, and continuous improvement. Raw request-response patterns lack the feedback loops needed to improve agent performance over time.

## Decision

**Adopt the SPAR (Sense-Plan-Act-Reflect) lifecycle** for all sessions:

| Phase | Component | Action |
|-------|-----------|--------|
| **Sense** | Planner | Parse query intent, identify drug/market/pillars |
| **Plan** | Decomposer | Generate task DAG with pillar-specific sub-tasks |
| **Act** | Retrievers + Supervisor + Executor | Execute tasks, validate, synthesize report |
| **Reflect** | ReflectionEngine | Post-session analysis: citations, coverage, consistency |

### Reflect Phase Details

The `ReflectionEngine` runs 5 checks after each session:
1. **Citation Validity** — Are all citations real and current?
2. **Timeout/Failure Detection** — Did any tasks DLQ or timeout?
3. **Decision Consistency** — Does the GO/NO-GO align with evidence?
4. **Pillar Coverage** — Did all expected pillars contribute?
5. **Improvement Suggestions** — What could be better next time?

## Consequences

- Reflections are persisted to PostgreSQL for trend analysis
- Dynamic thresholds can be loaded from Redis (per-user customization)
- DPO training pairs are collected from reflection data (chosen/rejected responses)
- The Reflect phase adds ~2s latency after session completion (acceptable — post-session)
