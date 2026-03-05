from __future__ import annotations

import io
import logging

from minio import Minio
from minio.error import S3Error

from src.shared.config import get_settings
from src.shared.ports.object_store import ObjectStore

logger = logging.getLogger(__name__)


class MinioObjectStore(ObjectStore):
    """S3-compatible object storage adapter backed by MinIO."""

    def __init__(self) -> None:
        cfg = get_settings().minio
        self._endpoint = cfg.endpoint
        self._bucket = cfg.bucket
        self._secure = cfg.secure
        self._client = Minio(
            endpoint=self._endpoint,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            secure=cfg.secure,
        )
        self._ready = False

    def ensure_ready(self) -> None:
        if self._ready:
            return
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
            self._ready = True
            logger.info("MinIO object store ready", extra={"bucket": self._bucket})
        except S3Error as exc:
            raise RuntimeError(f"MinIO bucket initialization failed: {exc}") from exc

    def upload_bytes(
        self,
        *,
        session_id: str,
        filename: str,
        payload: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        self.ensure_ready()
        object_name = f"reports/{session_id}/{filename}"
        data = io.BytesIO(payload)
        self._client.put_object(
            bucket_name=self._bucket,
            object_name=object_name,
            data=data,
            length=len(payload),
            content_type=content_type,
        )
        scheme = "https" if self._secure else "http"
        return f"{scheme}://{self._endpoint}/{self._bucket}/{object_name}"
