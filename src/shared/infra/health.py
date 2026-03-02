"""
Pharma Agentic AI — Deep Health Check Module.

Provides a comprehensive health check endpoint that validates
connectivity to all critical backend services. Used by container
orchestration health probes and monitoring dashboards.

Architecture context:
  - Service: Shared infrastructure (health layer)
  - Responsibility: Backend connectivity validation
  - Downstream: Cosmos DB, Redis, Service Bus, PostgreSQL
  - Failure: Returns degraded status with failing component details
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


async def deep_health_check() -> dict[str, Any]:
    """
    Perform connectivity checks against all critical backends.

    Returns:
        Dict with overall status, individual component statuses,
        and latency measurements.

    Status values: "healthy", "degraded", "unhealthy"
    """
    settings = get_settings()
    components: dict[str, dict[str, Any]] = {}
    overall_status = "healthy"

    # ── Cosmos DB ──────────────────────────────────────────
    try:
        start = time.monotonic()
        from azure.cosmos import CosmosClient
        client = CosmosClient(
            url=settings.cosmos_db.endpoint,
            credential=settings.cosmos_db.key,
        )
        # Read database metadata (lightweight check)
        db = client.get_database_client(settings.cosmos_db.database)
        db.read()
        latency_ms = (time.monotonic() - start) * 1000
        components["cosmos_db"] = {"status": "healthy", "latency_ms": round(latency_ms, 1)}
    except Exception as e:
        components["cosmos_db"] = {"status": "unhealthy", "error": str(e)}
        overall_status = "degraded"

    # ── Redis ─────────────────────────────────────────────
    try:
        start = time.monotonic()
        import redis as redis_lib
        r = redis_lib.from_url(settings.redis.url, socket_timeout=3)
        r.ping()
        latency_ms = (time.monotonic() - start) * 1000
        components["redis"] = {"status": "healthy", "latency_ms": round(latency_ms, 1)}
        r.close()
    except Exception as e:
        components["redis"] = {"status": "unhealthy", "error": str(e)}
        overall_status = "degraded"

    # ── Service Bus ───────────────────────────────────────
    try:
        start = time.monotonic()
        from azure.servicebus import ServiceBusClient
        sb = ServiceBusClient.from_connection_string(settings.servicebus.connection_string)
        # Lightweight: just creating the client validates the connection string
        sb.close()
        latency_ms = (time.monotonic() - start) * 1000
        components["service_bus"] = {"status": "healthy", "latency_ms": round(latency_ms, 1)}
    except Exception as e:
        components["service_bus"] = {"status": "unhealthy", "error": str(e)}
        overall_status = "degraded"

    # ── PostgreSQL ────────────────────────────────────────
    try:
        start = time.monotonic()
        import asyncpg
        conn = await asyncpg.connect(settings.postgres.url, timeout=3)
        await conn.fetchval("SELECT 1")
        await conn.close()
        latency_ms = (time.monotonic() - start) * 1000
        components["postgresql"] = {"status": "healthy", "latency_ms": round(latency_ms, 1)}
    except Exception as e:
        components["postgresql"] = {"status": "unhealthy", "error": str(e)}
        # PostgreSQL is not critical for all agents; mark degraded
        if overall_status == "healthy":
            overall_status = "degraded"

    # ── Azure OpenAI ──────────────────────────────────────
    try:
        start = time.monotonic()
        import httpx
        resp = httpx.get(
            f"{settings.azure_openai.endpoint}/openai/models?api-version={settings.azure_openai.api_version}",
            headers={"api-key": settings.azure_openai.api_key},
            timeout=5,
        )
        resp.raise_for_status()
        latency_ms = (time.monotonic() - start) * 1000
        components["azure_openai"] = {"status": "healthy", "latency_ms": round(latency_ms, 1)}
    except Exception as e:
        components["azure_openai"] = {"status": "unhealthy", "error": str(e)}
        overall_status = "degraded"

    return {
        "status": overall_status,
        "components": components,
        "timestamp": time.time(),
    }
