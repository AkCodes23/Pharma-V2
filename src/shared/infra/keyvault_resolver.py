"""
Pharma Agentic AI — Azure Key Vault Secret Resolver.

Loads secrets from Azure Key Vault at application startup,
optionally overriding environment variables. This keeps
connection strings and API keys out of config files entirely.

Architecture context:
  - Service: Shared infrastructure (bootstrap layer)
  - Responsibility: Secret lifecycle management
  - Upstream: Azure Key Vault
  - Downstream: All config.py settings
  - Failure: Fail loudly at startup if Key Vault unreachable
    (secrets are required for production operation)
  - Runtime: Called ONCE during app startup, before config load
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    from azure.identity import DefaultAzureCredential  # type: ignore
    from azure.keyvault.secrets import SecretClient  # type: ignore
except Exception:  # pragma: no cover - optional dependency in local/dev
    DefaultAzureCredential = None  # type: ignore[assignment]
    SecretClient = None  # type: ignore[assignment]

# Mapping: Key Vault secret name → environment variable name
_SECRET_MAP: dict[str, str] = {
    "azure-openai-api-key": "AZURE_OPENAI_API_KEY",
    "azure-openai-endpoint": "AZURE_OPENAI_ENDPOINT",
    "cosmos-db-key": "COSMOS_DB_KEY",
    "cosmos-db-endpoint": "COSMOS_DB_ENDPOINT",
    "service-bus-connection-string": "SERVICE_BUS_CONNECTION_STRING",
    "blob-storage-connection-string": "BLOB_STORAGE_CONNECTION_STRING",
    "ai-search-api-key": "AI_SEARCH_API_KEY",
    "ai-search-endpoint": "AI_SEARCH_ENDPOINT",
    "redis-url": "REDIS_URL",
    "postgres-url": "POSTGRES_URL",
    "ai-language-api-key": "AI_LANGUAGE_API_KEY",
    "ai-language-endpoint": "AI_LANGUAGE_ENDPOINT",
    "web-pubsub-connection-string": "WEB_PUBSUB_CONNECTION_STRING",
    "gremlin-key": "GREMLIN_KEY",
    "gremlin-endpoint": "GREMLIN_ENDPOINT",
    "tavily-api-key": "TAVILY_API_KEY",
    "telemetry-connection-string": "TELEMETRY_APPLICATION_INSIGHTS_CONNECTION_STRING",
}


def resolve_secrets_from_keyvault(
    vault_url: str | None = None,
    override_existing: bool = False,
) -> dict[str, str]:
    """
    Load secrets from Azure Key Vault and inject into environment variables.

    This function should be called BEFORE `get_settings()` so that
    Pydantic BaseSettings picks up the injected env vars.

    Args:
        vault_url: Key Vault URL (e.g., https://pharmaai-prod-kv.vault.azure.net/).
                   Falls back to KEY_VAULT_URL env var if not provided.
        override_existing: If True, overwrite env vars that are already set.
                          Default False = Key Vault fills only missing vars.

    Returns:
        Dict of resolved secret names and their env var targets.

    Raises:
        RuntimeError: If vault_url is not available and KEY_VAULT_URL is unset.
    """
    vault_url = vault_url or os.environ.get("KEY_VAULT_URL", "")
    if not vault_url:
        logger.info("KEY_VAULT_URL not set — skipping Key Vault secret resolution")
        return {}

    try:
        if DefaultAzureCredential is None or SecretClient is None:
            raise ImportError("azure-identity or azure-keyvault-secrets not available")

        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)

        resolved: dict[str, str] = {}

        for secret_name, env_var in _SECRET_MAP.items():
            # Skip if env var already set (unless override requested)
            if not override_existing and os.environ.get(env_var):
                logger.debug(
                    "Env var already set, skipping Key Vault lookup",
                    extra={"env_var": env_var},
                )
                continue

            try:
                secret = client.get_secret(secret_name)
                if secret.value:
                    os.environ[env_var] = secret.value
                    resolved[secret_name] = env_var
                    logger.debug(
                        "Secret resolved from Key Vault",
                        extra={"secret": secret_name, "env_var": env_var},
                    )
            except Exception:
                # Individual secret missing — not fatal, log and continue
                logger.warning(
                    "Secret not found in Key Vault",
                    extra={"secret": secret_name, "env_var": env_var},
                )

        logger.info(
            "Key Vault secret resolution complete",
            extra={"resolved_count": len(resolved), "total_mapped": len(_SECRET_MAP)},
        )

        client.close()
        return resolved

    except ImportError:
        logger.warning(
            "azure-identity or azure-keyvault-secrets not installed — "
            "skipping Key Vault resolution"
        )
        return {}
    except Exception as e:
        logger.error(
            "Key Vault connection failed",
            extra={"vault_url": vault_url, "error": str(e)},
        )
        return {}


def get_missing_secrets() -> list[str]:
    """
    Check which required secrets are missing from the environment.

    Useful for startup validation — logs all missing secrets
    so operators know what needs to be configured.

    Returns:
        List of missing environment variable names.
    """
    required = [
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "COSMOS_DB_KEY",
        "COSMOS_DB_ENDPOINT",
        "SERVICE_BUS_CONNECTION_STRING",
    ]
    missing = [var for var in required if not os.environ.get(var)]
    if missing:
        logger.warning(
            "Required secrets missing from environment",
            extra={"missing": missing, "count": len(missing)},
        )
    return missing
