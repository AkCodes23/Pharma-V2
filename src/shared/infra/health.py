"""Provider-aware deep health checks."""

from __future__ import annotations

import logging
import socket
import time
from typing import Any

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


def _check_tcp(host: str, port: int, timeout_seconds: float = 3.0) -> None:
    with socket.create_connection((host, port), timeout=timeout_seconds):
        return


async def _check_postgres(dsn: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(dsn, timeout=3)
    try:
        await conn.fetchval("SELECT 1")
    finally:
        await conn.close()


async def deep_health_check() -> dict[str, Any]:
    """Perform connectivity checks against provider-selected dependencies."""

    settings = get_settings()
    components: dict[str, dict[str, Any]] = {}
    overall_status = "healthy"

    # Data store check
    if settings.provider.data_store_provider.lower() == "postgres":
        try:
            start = time.monotonic()
            await _check_postgres(settings.postgres.url)
            components["postgresql"] = {
                "status": "healthy",
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
            }
        except Exception as exc:
            components["postgresql"] = {"status": "unhealthy", "error": str(exc)}
            overall_status = "degraded"
    else:
        try:
            start = time.monotonic()
            from azure.cosmos import CosmosClient

            client = CosmosClient(url=settings.cosmos.endpoint, credential=settings.cosmos.key)
            db = client.get_database_client(settings.cosmos.database_name)
            db.read()
            components["cosmos_db"] = {
                "status": "healthy",
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
            }
        except Exception as exc:
            components["cosmos_db"] = {"status": "unhealthy", "error": str(exc)}
            overall_status = "degraded"

    # Redis check
    try:
        start = time.monotonic()
        import redis as redis_lib

        redis_client = redis_lib.from_url(settings.redis.url, socket_timeout=3)
        redis_client.ping()
        redis_client.close()
        components["redis"] = {
            "status": "healthy",
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
        }
    except Exception as exc:
        components["redis"] = {"status": "unhealthy", "error": str(exc)}
        overall_status = "degraded"

    # Task bus check
    if settings.provider.task_bus_provider.lower() == "kafka":
        try:
            start = time.monotonic()
            first_broker = settings.kafka.bootstrap_servers.split(",")[0].strip()
            host, port_text = first_broker.split(":", 1)
            _check_tcp(host, int(port_text))
            components["kafka"] = {
                "status": "healthy",
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
            }
        except Exception as exc:
            components["kafka"] = {"status": "unhealthy", "error": str(exc)}
            overall_status = "degraded"
    else:
        try:
            start = time.monotonic()
            from azure.servicebus import ServiceBusClient

            client = ServiceBusClient.from_connection_string(settings.servicebus.connection_string)
            client.close()
            components["service_bus"] = {
                "status": "healthy",
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
            }
        except Exception as exc:
            components["service_bus"] = {"status": "unhealthy", "error": str(exc)}
            overall_status = "degraded"

    # Object storage check
    if settings.provider.object_store_provider.lower() == "minio":
        try:
            start = time.monotonic()
            from minio import Minio

            client = Minio(
                endpoint=settings.minio.endpoint,
                access_key=settings.minio.access_key,
                secret_key=settings.minio.secret_key,
                secure=settings.minio.secure,
            )
            client.bucket_exists(settings.minio.bucket)
            components["minio"] = {
                "status": "healthy",
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
            }
        except Exception as exc:
            components["minio"] = {"status": "unhealthy", "error": str(exc)}
            overall_status = "degraded"
    else:
        try:
            start = time.monotonic()
            from azure.storage.blob import BlobServiceClient

            client = BlobServiceClient.from_connection_string(settings.blob.connection_string)
            container = client.get_container_client(settings.blob.reports_container)
            container.exists()
            components["blob_storage"] = {
                "status": "healthy",
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
            }
        except Exception as exc:
            components["blob_storage"] = {"status": "unhealthy", "error": str(exc)}
            overall_status = "degraded"

    # LLM check (skipped in standalone fixture mode)
    if settings.provider.llm_provider.lower() in {"fixture", "mock"}:
        components["llm"] = {"status": "healthy", "mode": "fixture"}
    else:
        try:
            start = time.monotonic()
            import httpx

            response = httpx.get(
                f"{settings.azure_openai.endpoint}/openai/models?api-version={settings.azure_openai.api_version}",
                headers={"api-key": settings.azure_openai.api_key},
                timeout=5,
            )
            response.raise_for_status()
            components["azure_openai"] = {
                "status": "healthy",
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
            }
        except Exception as exc:
            components["azure_openai"] = {"status": "unhealthy", "error": str(exc)}
            overall_status = "degraded"

    return {
        "status": overall_status,
        "components": components,
        "timestamp": time.time(),
    }
