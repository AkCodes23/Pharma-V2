# ADR-006: Context-Constrained Decoding for Report Generation

**Status:** Accepted  
**Date:** 2026-03-02  
**Decision Makers:** AI Engineering Team

## Context

The Executor Agent generates executive reports from validated agent results. The LLM (GPT-4o) must:

1. Use ONLY information from agent results — no hallucination
2. Cite every factual claim with a source reference
3. Produce deterministic GO/NO-GO decisions based on evidence
4. Handle missing pillar data gracefully (INSUFFICIENT DATA label)

## Decision

**Use Context-Constrained Decoding (CCD)** — a prompt engineering technique that:

1. Provides all agent results as structured context in the system prompt
2. Instructs the LLM with strict rules: "Use ONLY the provided context"
3. Requires inline citation markers (`[Source Name]`) for every claim
4. Separates the GO/NO-GO decision from the LLM — determined by a deterministic function based on grounding score and conflict severity

### Decision Logic (Deterministic)

```python
def _determine_decision(session):
    if critical_conflicts:          → NO_GO
    if grounding_score >= 0.7:      → GO
    if grounding_score >= 0.5:      → CONDITIONAL
    else:                           → NO_GO
```

## Consequences

- LLM generates only the narrative text; the decision is never delegated to the LLM
- Missing pillars are labeled `INSUFFICIENT DATA` rather than fabricated
- Citation registry in the PDF includes source_url, retrieved_at, and data_hash
- Temperature is set to 0.0 for maximum determinism
