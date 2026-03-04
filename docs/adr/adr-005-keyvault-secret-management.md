# ADR-005: Key Vault Secret Management via Bootstrap

Status: Accepted
Date: 2026-03-02
Decision owners: Platform Engineering, Security

## Context

The system relies on multiple credentials and connection secrets across OpenAI, Cosmos, Service Bus, storage, and supporting services. Secret sprawl across images and static files increases risk.

Requirements:
1. avoid embedding secrets in images and source
2. support central rotation and least privilege
3. provide deterministic startup behavior when secrets are missing

## Decision

Use Azure Key Vault as the production secret authority.

Runtime approach:
1. service startup invokes bootstrap
2. bootstrap resolves secrets from Key Vault into process environment
3. typed settings load and validate config
4. startup fails fast when required production secrets are absent

Development mode can use `.env` directly.

## Alternatives Considered

1. static `.env` only
- Pros: simple
- Cons: weak security and rotation controls

2. orchestrator-native secret injection only
- Pros: platform-native
- Cons: less portable across local/container apps/k8s workflows

3. Key Vault bootstrap (chosen)
- Pros: centralized lifecycle, explicit startup validation, cloud-native security model
- Cons: startup dependency on Key Vault availability

## Consequences

Positive:
- clearer secret lifecycle and auditability
- safer credential handling in production

Tradeoffs:
- bootstrap failures can block startup if Key Vault unreachable
- secret map maintenance required for newly added config keys

## Verification

1. verify managed identity has key vault access policy/RBAC
2. verify bootstrap logs successful resolution
3. verify settings load does not rely on hardcoded secrets

## Rollback

If Key Vault path is unavailable:
1. temporarily switch to env-driven fallback for critical services
2. restore Key Vault connectivity and permissions
3. remove fallback once stable
