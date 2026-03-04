# ADR-006: Context-Constrained Decoding for Report Synthesis

Status: Accepted
Date: 2026-03-02
Decision owners: AI Engineering

## Context

Executive report generation requires grounded synthesis from agent outputs. Unconstrained generation can introduce unsupported claims and weaken decision trust.

Requirements:
1. report narrative must be based on retrieved evidence
2. decision outcomes must be deterministic and auditable
3. missing data must be explicit, not fabricated

## Decision

Use context-constrained decoding (CCD) in executor report generation:
- feed structured validated results as context
- constrain prompt behavior to context-derived claims
- require explicit citation-linked narrative sections
- keep final decision logic deterministic and outside free-form generation

## Alternatives Considered

1. unconstrained generative report
- Pros: flexible language
- Cons: hallucination risk and weak auditability

2. template-only report with no LLM synthesis
- Pros: deterministic
- Cons: poor readability and weak narrative quality

3. constrained synthesis with deterministic decision (chosen)
- Pros: balanced readability + control + traceability
- Cons: prompt maintenance overhead

## Consequences

Positive:
- lower hallucination risk in final artifacts
- clearer evidence-to-decision trace

Tradeoffs:
- prompt complexity increases
- stricter constraints can reduce narrative flexibility

## Verification

1. ensure executor decision path is deterministic in code.
2. verify report sections reference available result fields.
3. test missing-pillar scenarios for explicit data gaps.

## Rollback

If constrained prompt causes unacceptable report quality:
1. adjust prompt constraints incrementally
2. keep deterministic decision path unchanged
3. avoid reverting to unconstrained generation
