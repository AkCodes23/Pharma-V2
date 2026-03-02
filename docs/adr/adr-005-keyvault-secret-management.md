# ADR-005: Azure Key Vault for Secret Lifecycle Management

**Status:** Accepted  
**Date:** 2026-03-02  
**Decision Makers:** Platform Engineering Team

## Context

The platform connects to 12+ Azure services, each requiring credentials (API keys, connection strings, endpoints). We need a secrets management strategy that:

1. Keeps secrets out of environment files and container images
2. Supports rotation without redeployment
3. Works with Azure Managed Identity (no stored credentials)
4. Fails safely — agents must not start with missing critical secrets

## Decision

**Use Azure Key Vault as the single source of truth for all secrets**, resolved at agent startup via `bootstrap_agent()` → `resolve_secrets_from_keyvault()`. The only environment variable needed in production is `KEY_VAULT_URL`.

### Resolution Flow

```
Agent Startup
  → bootstrap_agent()
    → resolve_secrets_from_keyvault()  [reads Key Vault, injects into os.environ]
    → get_settings()                   [Pydantic picks up injected env vars]
    → validate critical secrets         [fail-fast in production if missing]
    → setup_telemetry()
```

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| .env files in containers | Simple, no network calls | Secrets in image layers, no rotation |
| K8s Secrets + CSI driver | K8s-native, auto-mount | Tied to K8s, not portable to Container Apps |
| **Key Vault + bootstrap** ✅ | Centralized, rotation-ready, works with ACA + AKS | Startup latency (~500ms), Key Vault dependency |

## Consequences

- Every agent must call `bootstrap_agent()` as the first action in its lifespan
- `_SECRET_MAP` in `keyvault_resolver.py` must be updated when new secrets are added
- Production agents fail-fast if critical secrets (OpenAI, Cosmos, Service Bus) are missing
- Development mode uses `.env` files and silently skips Key Vault resolution
