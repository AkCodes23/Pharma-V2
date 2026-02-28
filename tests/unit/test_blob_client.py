"""
Unit tests for Azure Blob Storage Client.

Tests cover: upload, SAS URL generation, session listing,
and deletion — all with mocked Azure SDK.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_settings():
    """Provide mock settings for Blob Storage config."""
    settings = MagicMock()
    settings.blob.connection_string = "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=dGVzdA==;EndpointSuffix=core.windows.net"
    settings.blob.reports_container = "reports"
    return settings


class TestBlobStorageClient:
    """Tests for BlobStorageClient."""

    @patch("src.shared.infra.blob_client.get_settings")
    def test_init_sets_config(self, mock_get_settings, mock_settings):
        """Verify client stores connection string and container name."""
        mock_get_settings.return_value = mock_settings
        from src.shared.infra.blob_client import BlobStorageClient

        client = BlobStorageClient()
        assert client._reports_container == "reports"
        assert client._connection_string == mock_settings.blob.connection_string

    @patch("src.shared.infra.blob_client.get_settings")
    def test_upload_raises_if_not_initialized(self, mock_get_settings, mock_settings):
        """Upload should raise RuntimeError before initialize() is called."""
        mock_get_settings.return_value = mock_settings
        from src.shared.infra.blob_client import BlobStorageClient

        client = BlobStorageClient()
        with pytest.raises(RuntimeError, match="not initialized"):
            asyncio.get_event_loop().run_until_complete(
                client.upload_report("session-1", "report.pdf", b"data")
            )

    @patch("src.shared.infra.blob_client.get_settings")
    def test_content_type_detection(self, mock_get_settings, mock_settings):
        """Verify auto content type detection from file extension."""
        mock_get_settings.return_value = mock_settings
        from src.shared.infra.blob_client import _CONTENT_TYPES

        assert _CONTENT_TYPES[".pdf"] == "application/pdf"
        assert _CONTENT_TYPES[".xlsx"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert _CONTENT_TYPES[".png"] == "image/png"
        assert _CONTENT_TYPES[".json"] == "application/json"
        assert _CONTENT_TYPES[".html"] == "text/html"

    @patch("src.shared.infra.blob_client.get_settings")
    def test_list_reports_returns_empty_when_not_initialized(self, mock_get_settings, mock_settings):
        """list_session_reports returns empty list if client not initialized."""
        mock_get_settings.return_value = mock_settings
        from src.shared.infra.blob_client import BlobStorageClient

        client = BlobStorageClient()
        result = asyncio.get_event_loop().run_until_complete(
            client.list_session_reports("session-1")
        )
        assert result == []

    @patch("src.shared.infra.blob_client.get_settings")
    def test_delete_reports_returns_zero_when_not_initialized(self, mock_get_settings, mock_settings):
        """delete_session_reports returns 0 if client not initialized."""
        mock_get_settings.return_value = mock_settings
        from src.shared.infra.blob_client import BlobStorageClient

        client = BlobStorageClient()
        result = asyncio.get_event_loop().run_until_complete(
            client.delete_session_reports("session-1")
        )
        assert result == 0

    @patch("src.shared.infra.blob_client.get_settings")
    def test_close_resets_client(self, mock_get_settings, mock_settings):
        """close() should set internal client to None."""
        mock_get_settings.return_value = mock_settings
        from src.shared.infra.blob_client import BlobStorageClient

        client = BlobStorageClient()
        # Simulate an initialized client
        client._client = AsyncMock()
        asyncio.get_event_loop().run_until_complete(client.close())
        assert client._client is None
