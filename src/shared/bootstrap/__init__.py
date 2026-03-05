"""Agent bootstrap module."""

from __future__ import annotations

import logging

from src.shared.config import Settings, get_settings
from src.shared.infra.keyvault_resolver import get_missing_secrets, resolve_secrets_from_keyvault

logger = logging.getLogger(__name__)


def _validate_broker_mode(settings: Settings, agent_name: str) -> None:
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
            "Verify selected task bus provider for this deployment.",
            extra={"agent": agent_name},
        )


def bootstrap_agent(
    agent_name: str = "unknown",
    fail_on_missing_secrets: bool | None = None,
) -> Settings:
    """Shared bootstrap sequence for all services."""

    logger.info("Bootstrapping agent: %s", agent_name)

    resolved = resolve_secrets_from_keyvault()
    if resolved:
        logger.info(
            "Key Vault secrets resolved",
            extra={"agent": agent_name, "count": len(resolved)},
        )

    settings = get_settings()
    settings.validate_startup()
    _validate_broker_mode(settings, agent_name)

    is_production = settings.app.env.lower() in ("production", "prod", "staging")
    should_fail = fail_on_missing_secrets if fail_on_missing_secrets is not None else is_production

    missing: list[str] = []
    if not settings.provider.is_standalone_demo:
        missing = get_missing_secrets()

    if missing and should_fail:
        raise RuntimeError(
            f"Agent '{agent_name}' cannot start: missing critical secrets: {missing}. "
            "Ensure KEY_VAULT_URL is set and secrets are seeded in Key Vault."
        )
    if missing:
        logger.warning(
            "Non-critical secret gaps detected",
            extra={"agent": agent_name, "missing": missing},
        )

    try:
        from src.shared.infra.telemetry import setup_telemetry

        setup_telemetry(settings)
        logger.info("Telemetry initialized", extra={"agent": agent_name})
    except Exception:
        logger.warning(
            "Telemetry initialization failed - continuing without observability",
            extra={"agent": agent_name},
            exc_info=True,
        )

    logger.info(
        "Agent bootstrap complete",
        extra={
            "agent": agent_name,
            "environment": settings.app.env,
            "app_mode": settings.provider.app_mode,
            "kv_secrets_resolved": len(resolved),
            "missing_secrets": len(missing),
        },
    )

    return settings
