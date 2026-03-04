"""
Pharma Agentic AI — Agent Bootstrap Module.

Provides a shared bootstrap sequence for all agent services.
Ensures Key Vault secrets are resolved BEFORE config loads,
telemetry is initialized, and startup is validated.

Architecture context:
  - Service: Shared infrastructure (bootstrap layer)
  - Responsibility: Ordered startup initialization
  - Upstream: Azure Key Vault, environment variables
  - Downstream: All agent main modules
  - Failure: Fail-fast on missing critical secrets (production)

Call `bootstrap_agent()` as the FIRST action in every agent's
lifespan function, before accessing any config values.
"""

from __future__ import annotations

import logging

from src.shared.config import Settings, get_settings
from src.shared.infra.keyvault_resolver import get_missing_secrets, resolve_secrets_from_keyvault

logger = logging.getLogger(__name__)


def _validate_broker_mode(settings: Settings, agent_name: str) -> None:
    """Fail fast on incompatible message-bus mode configuration."""
    kafka_cfg = settings.kafka
    servicebus_cfg = settings.servicebus

    if kafka_cfg.use_event_hubs and not kafka_cfg.event_hubs_connection_string:
        raise RuntimeError(
            f"Agent '{agent_name}' has KAFKA_USE_EVENT_HUBS=true but "
            "KAFKA_EVENT_HUBS_CONNECTION_STRING is missing."
        )

    if kafka_cfg.use_event_hubs and servicebus_cfg.connection_string:
        logger.warning(
            "Both Kafka(Event Hubs) and Service Bus credentials are configured. "
            "Retriever runtime currently consumes from Service Bus; verify deployment mode.",
            extra={"agent": agent_name},
        )


def bootstrap_agent(
    agent_name: str = "unknown",
    fail_on_missing_secrets: bool | None = None,
) -> Settings:
    """
    Shared bootstrap sequence for all Pharma AI agents.

    Execution order:
      1. Resolve secrets from Azure Key Vault (if KEY_VAULT_URL set)
      2. Load validated settings via Pydantic BaseSettings
      3. Check for missing critical secrets
      4. Initialize telemetry (OpenTelemetry + Azure Monitor)

    Args:
        agent_name: Human-readable agent identifier for logging.
        fail_on_missing_secrets: If True, raise on missing critical secrets.
            Defaults to True in production, False in development.

    Returns:
        Validated Settings object with all config loaded.

    Raises:
        RuntimeError: In production mode, if critical secrets are missing
            after Key Vault resolution.
    """
    logger.info("Bootstrapping agent: %s", agent_name)

    # Step 1: Resolve secrets from Key Vault (injects into os.environ)
    resolved = resolve_secrets_from_keyvault()
    if resolved:
        logger.info(
            "Key Vault secrets resolved",
            extra={"agent": agent_name, "count": len(resolved)},
        )

    # Step 2: Load settings (Pydantic picks up env vars including KV-injected ones)
    settings = get_settings()
    _validate_broker_mode(settings, agent_name)

    # Step 3: Validate critical secrets
    is_production = settings.app.env.lower() in ("production", "prod", "staging")
    should_fail = fail_on_missing_secrets if fail_on_missing_secrets is not None else is_production

    missing = get_missing_secrets()
    if missing and should_fail:
        raise RuntimeError(
            f"Agent '{agent_name}' cannot start: missing critical secrets: {missing}. "
            f"Ensure KEY_VAULT_URL is set and secrets are seeded in Key Vault."
        )
    elif missing:
        logger.warning(
            "Non-critical secret gaps detected (development mode)",
            extra={"agent": agent_name, "missing": missing},
        )

    # Step 4: Initialize telemetry
    try:
        from src.shared.infra.telemetry import setup_telemetry
        setup_telemetry(settings)
        logger.info("Telemetry initialized", extra={"agent": agent_name})
    except Exception:
        logger.warning(
            "Telemetry initialization failed — continuing without observability",
            extra={"agent": agent_name},
            exc_info=True,
        )

    logger.info(
        "Agent bootstrap complete",
        extra={
            "agent": agent_name,
            "environment": settings.app.env,
            "kv_secrets_resolved": len(resolved),
            "missing_secrets": len(missing),
        },
    )

    return settings
