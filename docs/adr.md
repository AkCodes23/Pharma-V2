# Architecture Decision Records (ADR)

This directory records major architecture choices that affect long-term system behavior.

## ADR Process

When to create/update an ADR:
- introducing or replacing core infrastructure components
- changing service contracts that affect multiple services
- changing data flow, fault-tolerance strategy, or scaling model
- introducing high-impact operational/security behavior

ADR format:
1. Status
2. Date
3. Context
4. Decision
5. Alternatives considered
6. Consequences
7. Verification and rollback

## Current ADRs

- `adr-004-servicebus-topic-per-pillar.md`
- `adr-005-keyvault-secret-management.md`
- `adr-006-context-constrained-decoding.md`
- `adr-007-spar-lifecycle.md`

Historical records in this repository root file are retained but should be migrated to one-file-per-ADR where practical.

## ADR Change Control

Any ADR update should include:
- linked code/config changes
- migration notes if behavior changed
- explicit rollback path
