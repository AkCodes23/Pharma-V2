"""
Pharma Agentic AI — Azure Blob Storage Client.

Handles upload and URL generation for PDF reports, Excel exports,
and any file artifacts produced by the Executor agent.

Architecture context:
  - Service: Shared infrastructure
  - Responsibility: File storage for generated reports
  - Upstream: Executor agent (PDF engine, chart generator)
  - Downstream: Azure Blob Storage (Storage Account)
  - Data ownership: Report artifacts (PDF, XLSX, PNG charts)
  - Failure: Upload failures are retried 3x; final failure
    logged with session context but does NOT block session completion.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

from azure.storage.blob.aio import BlobServiceClient, ContainerClient
from azure.storage.blob import (
    BlobSasPermissions,
    ContentSettings,
    generate_blob_sas,
)

from src.shared.config import get_settings

logger = logging.getLogger(__name__)

# Content type mapping for uploads
_CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".json": "application/json",
    ".html": "text/html",
}


class BlobStorageClient:
    """
    Azure Blob Storage client for report artifact management.

    Provides:
      1. Upload PDF/Excel/Chart files → Blob Storage
      2. Generate time-limited SAS URLs for download
      3. List/delete reports by session

    Thread-safe: Azure SDK handles connection pooling internally.
    """

    def __init__(self) -> None:
        settings = get_settings()
        blob_cfg = settings.blob

        self._connection_string = blob_cfg.connection_string
        self._reports_container = blob_cfg.reports_container
        self._client: BlobServiceClient | None = None

    async def initialize(self) -> None:
        """
        Initialize the async Blob Service client and ensure container exists.

        Must be called once at application startup.
        """
        self._client = BlobServiceClient.from_connection_string(
            self._connection_string
        )
        # Ensure reports container exists
        try:
            container: ContainerClient = self._client.get_container_client(
                self._reports_container
            )
            if not await container.exists():
                await container.create_container()
                logger.info(
                    "Created blob container",
                    extra={"container": self._reports_container},
                )
        except Exception:
            logger.exception("Failed to initialize blob container")

        logger.info("BlobStorageClient initialized")

    async def upload_report(
        self,
        session_id: str,
        filename: str,
        data: bytes | BytesIO,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """
        Upload a report file to Blob Storage.

        Args:
            session_id: Session UUID (used as folder prefix).
            filename: Target filename (e.g., 'report.pdf').
            data: File content as bytes or BytesIO.
            content_type: MIME type (auto-detected from extension if omitted).
            metadata: Optional blob metadata tags.

        Returns:
            Full blob URL (without SAS token).

        Raises:
            RuntimeError: If client not initialized.
        """
        if not self._client:
            raise RuntimeError("BlobStorageClient not initialized. Call initialize() first.")

        # Auto-detect content type from extension
        if content_type is None:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")

        blob_path = f"{session_id}/{filename}"
        blob_metadata = {
            "session_id": session_id,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }

        container = self._client.get_container_client(self._reports_container)
        blob = container.get_blob_client(blob_path)

        # Upload with retry (Azure SDK handles retries internally)
        content_settings = ContentSettings(content_type=content_type)
        upload_data = data if isinstance(data, bytes) else data.read()

        await blob.upload_blob(
            upload_data,
            overwrite=True,
            content_settings=content_settings,
            metadata=blob_metadata,
        )

        logger.info(
            "Report uploaded to Blob Storage",
            extra={
                "session_id": session_id,
                "blob_path": blob_path,
                "size_bytes": len(upload_data),
                "content_type": content_type,
            },
        )

        return blob.url

    async def generate_download_url(
        self,
        session_id: str,
        filename: str,
        expiry_hours: int = 24,
    ) -> str:
        """
        Generate a time-limited SAS URL for downloading a report.

        Args:
            session_id: Session UUID.
            filename: Target filename.
            expiry_hours: URL validity in hours (default 24h).

        Returns:
            Blob URL with SAS token appended.
        """
        if not self._client:
            raise RuntimeError("BlobStorageClient not initialized.")

        blob_path = f"{session_id}/{filename}"

        # Parse account details from connection string for SAS generation
        from azure.storage.blob import BlobServiceClient as SyncBlobClient
        sync_client = SyncBlobClient.from_connection_string(self._connection_string)
        account_name = sync_client.account_name
        account_key = sync_client.credential.account_key

        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=self._reports_container,
            blob_name=blob_path,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
        )

        container = self._client.get_container_client(self._reports_container)
        blob = container.get_blob_client(blob_path)

        return f"{blob.url}?{sas_token}"

    async def list_session_reports(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        """
        List all report artifacts for a given session.

        Returns:
            List of dicts: {name, size, content_type, last_modified}
        """
        if not self._client:
            return []

        container = self._client.get_container_client(self._reports_container)
        prefix = f"{session_id}/"

        reports = []
        async for blob_props in container.list_blobs(name_starts_with=prefix):
            reports.append({
                "name": blob_props.name.removeprefix(prefix),
                "size": blob_props.size,
                "content_type": blob_props.content_settings.content_type
                if blob_props.content_settings else "unknown",
                "last_modified": blob_props.last_modified.isoformat()
                if blob_props.last_modified else None,
            })

        return reports

    async def delete_session_reports(self, session_id: str) -> int:
        """
        Delete all report artifacts for a session (cleanup).

        Returns:
            Number of blobs deleted.
        """
        if not self._client:
            return 0

        container = self._client.get_container_client(self._reports_container)
        prefix = f"{session_id}/"

        count = 0
        async for blob_props in container.list_blobs(name_starts_with=prefix):
            await container.delete_blob(blob_props.name)
            count += 1

        if count:
            logger.info(
                "Deleted session reports",
                extra={"session_id": session_id, "count": count},
            )
        return count

    async def close(self) -> None:
        """Close the async Blob Service client."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("BlobStorageClient closed")
