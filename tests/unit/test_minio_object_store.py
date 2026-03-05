from __future__ import annotations

import sys
import types

if "minio" not in sys.modules:
    minio_stub = types.ModuleType("minio")

    class _FakeMinio:
        def __init__(self, *args, **kwargs):
            return

    minio_stub.Minio = _FakeMinio
    sys.modules["minio"] = minio_stub

if "minio.error" not in sys.modules:
    minio_error_stub = types.ModuleType("minio.error")

    class _FakeS3Error(Exception):
        pass

    minio_error_stub.S3Error = _FakeS3Error
    sys.modules["minio.error"] = minio_error_stub
from unittest.mock import MagicMock

from src.shared.adapters.minio_object_store import MinioObjectStore


class _DummyMinioSettings:
    endpoint = "minio:9000"
    access_key = "minioadmin"
    secret_key = "minioadmin"
    bucket = "reports"
    secure = False


class _DummySettings:
    minio = _DummyMinioSettings()


def test_minio_object_store_ensures_bucket(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.shared.adapters.minio_object_store.get_settings",
        lambda: _DummySettings(),
    )

    store = MinioObjectStore()
    client = MagicMock()
    client.bucket_exists.return_value = False
    store._client = client

    store.ensure_ready()

    client.make_bucket.assert_called_once_with("reports")


def test_minio_object_store_upload_returns_object_url(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.shared.adapters.minio_object_store.get_settings",
        lambda: _DummySettings(),
    )

    store = MinioObjectStore()
    client = MagicMock()
    client.bucket_exists.return_value = True
    store._client = client

    url = store.upload_bytes(
        session_id="s-1",
        filename="report.pdf",
        payload=b"pdf-bytes",
        content_type="application/pdf",
    )

    assert url == "http://minio:9000/reports/reports/s-1/report.pdf"
    client.put_object.assert_called_once()

