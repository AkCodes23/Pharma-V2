# ADR-007: SPAR Lifecycle for Session Orchestration

Status: Accepted
Date: 2026-03-02
Decision owners: AI Engineering

## Context

A multi-agent workflow requires a lifecycle model that supports execution quality controls and post-run learning. Pure request-response orchestration does not capture reflection and improvement signals well.

Requirements:
1. clear execution phases
2. explicit validation and synthesis checkpoints
3. post-session quality reflection for iterative improvement

## Decision

Adopt SPAR lifecycle model:
- Sense: parse user intent and context
- Plan: generate task graph
- Act: execute retrievers, validate, synthesize
- Reflect: evaluate quality and consistency post-run

Reflection outputs are stored for analysis and future training/optimization workflows.

## Alternatives Considered

1. linear orchestration without reflection
- Pros: simpler
- Cons: no structured learning feedback loop

2. ad-hoc per-service metrics only
- Pros: lightweight
- Cons: fragmented quality signal and weak session-level insight

3. SPAR lifecycle (chosen)
- Pros: coherent control model with learning path
- Cons: additional implementation complexity

## Consequences

Positive:
- consistent lifecycle framing across services
- better support for quality trend analysis

Tradeoffs:
- requires additional storage/processing for reflection artifacts
- introduces extra operational surfaces

## Verification

1. confirm session progresses through planned lifecycle checkpoints.
2. confirm reflection data persists for completed sessions.
3. confirm reflection failures do not block critical completion paths unless explicitly required.

## Rollback

If reflection causes instability:
1. disable reflection execution path behind feature/config controls
2. preserve core Sense-Plan-Act flow
3. re-enable after corrective changes and validation
