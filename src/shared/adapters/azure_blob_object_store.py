from __future__ import annotations

import io

from azure.storage.blob import BlobServiceClient, ContentSettings

from src.shared.config import get_settings
from src.shared.ports.object_store import ObjectStore


class AzureBlobObjectStore(ObjectStore):
    """Synchronous ObjectStore adapter backed by Azure Blob Storage."""

    def __init__(self) -> None:
        cfg = get_settings().blob
        self._connection_string = cfg.connection_string
        self._container_name = cfg.reports_container
        self._client: BlobServiceClient | None = None
        self._container = None
        self._ready = False

    def ensure_ready(self) -> None:
        if self._ready:
            return
        if not self._connection_string:
            raise RuntimeError("BLOB_STORAGE_CONNECTION_STRING is required for Azure blob provider")
        self._client = BlobServiceClient.from_connection_string(self._connection_string)
        container = self._client.get_container_client(self._container_name)
        self._container = container
        if not self._container.exists():
            self._container.create_container()
        self._ready = True

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
        blob = self._container.get_blob_client(object_name)
        blob.upload_blob(
            io.BytesIO(payload),
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )
        return blob.url
