from __future__ import annotations

import pytest

from src.shared.config import get_settings
from src.shared.infra.network_guard import assert_url_allowed_for_demo


def test_network_guard_blocks_azure_domains_in_demo_mode(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_MODE", "standalone_demo")
    monkeypatch.setenv("DEMO_OFFLINE", "true")
    monkeypatch.setenv("DATA_STORE_PROVIDER", "postgres")
    monkeypatch.setenv("TASK_BUS_PROVIDER", "kafka")
    monkeypatch.setenv("OBJECT_STORE_PROVIDER", "minio")
    monkeypatch.setenv("LLM_PROVIDER", "fixture")
    monkeypatch.setenv("KNOWLEDGE_PROVIDER", "fixture")
    monkeypatch.setenv("AUTH_MODE", "anonymous")
    monkeypatch.setenv("MINIO_ENDPOINT", "minio:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_SECRET_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_BUCKET", "reports")
    monkeypatch.setenv("POSTGRES_URL", "postgresql://pharma:pass@localhost:5432/pharma_ai")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    monkeypatch.setenv("SUPERVISOR_URL", "http://localhost:8001")
    monkeypatch.setenv("EXECUTOR_URL", "http://localhost:8002")

    with pytest.raises(RuntimeError, match="blocks outbound request"):
        assert_url_allowed_for_demo("https://example.openai.azure.com/openai/deployments/gpt-4o")


def test_network_guard_allows_local_domains(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_MODE", "standalone_demo")
    monkeypatch.setenv("DEMO_OFFLINE", "true")
    monkeypatch.setenv("DATA_STORE_PROVIDER", "postgres")
    monkeypatch.setenv("TASK_BUS_PROVIDER", "kafka")
    monkeypatch.setenv("OBJECT_STORE_PROVIDER", "minio")
    monkeypatch.setenv("LLM_PROVIDER", "fixture")
    monkeypatch.setenv("KNOWLEDGE_PROVIDER", "fixture")
    monkeypatch.setenv("AUTH_MODE", "anonymous")
    monkeypatch.setenv("MINIO_ENDPOINT", "minio:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_SECRET_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_BUCKET", "reports")
    monkeypatch.setenv("POSTGRES_URL", "postgresql://pharma:pass@localhost:5432/pharma_ai")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    monkeypatch.setenv("SUPERVISOR_URL", "http://localhost:8001")
    monkeypatch.setenv("EXECUTOR_URL", "http://localhost:8002")

    assert_url_allowed_for_demo("http://localhost:8000/health")
