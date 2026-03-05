from __future__ import annotations

import pytest

from src.shared.config import get_settings


REQUIRED_DEMO_ENV = {
    "APP_MODE": "standalone_demo",
    "DEMO_OFFLINE": "true",
    "DATA_STORE_PROVIDER": "postgres",
    "TASK_BUS_PROVIDER": "kafka",
    "OBJECT_STORE_PROVIDER": "minio",
    "LLM_PROVIDER": "fixture",
    "KNOWLEDGE_PROVIDER": "fixture",
    "AUTH_MODE": "anonymous",
    "POSTGRES_URL": "postgresql://pharma:pass@localhost:5432/pharma_ai",
    "REDIS_URL": "redis://localhost:6379/0",
    "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
    "MINIO_ACCESS_KEY": "minioadmin",
    "MINIO_SECRET_KEY": "minioadmin",
    "MINIO_BUCKET": "reports",
    "SUPERVISOR_URL": "http://localhost:8001",
    "EXECUTOR_URL": "http://localhost:8002",
}


def test_missing_env_fails_fast_for_demo_mode(monkeypatch) -> None:
    get_settings.cache_clear()
    for key, value in REQUIRED_DEMO_ENV.items():
        monkeypatch.setenv(key, value)

    # Intentionally omit MINIO_ENDPOINT to verify fail-fast validation.
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)

    settings = get_settings()

    with pytest.raises(RuntimeError, match="MINIO_ENDPOINT"):
        settings.validate_startup()
