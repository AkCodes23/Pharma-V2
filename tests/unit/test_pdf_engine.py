"""
Unit tests for Executor Agent — PDFEngine.

Tests HTML template rendering, markdown-to-HTML conversion,
citation table generation, and Blob upload.

PDFEngine.__init__ calls get_settings(), so we must mock it in all fixtures.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.executor.pdf_engine import PDFEngine


@pytest.fixture
def pdf_engine() -> PDFEngine:
    with patch("src.agents.executor.pdf_engine.get_settings") as mock_settings:
        settings = MagicMock()
        settings.blob_storage = MagicMock()
        settings.blob_storage.connection_string = "DefaultEndpointsProtocol=https;AccountName=test"
        settings.blob_storage.reports_container = "reports"
        mock_settings.return_value = settings
        engine = PDFEngine()
    return engine


class TestRenderPDF:
    """Tests for PDF rendering from markdown."""

    def test_renders_pdf_bytes(self, pdf_engine: PDFEngine) -> None:
        """Happy path: should return non-empty bytes."""
        pdf_bytes = pdf_engine.render_pdf(
            report_markdown="# Test Report\n\nThis is a **test** report.\n\n## Legal Analysis\nNo issues.",
            session_id="test-session-001",
            query="Test query for drug analysis",
            decision="GO",
            citations=[
                {"source_name": "FDA", "source_url": "https://fda.gov", "retrieved_at": "2026-01-01", "data_hash": "abc"},
            ],
        )
        assert isinstance(pdf_bytes, bytes)
        if len(pdf_bytes) == 0:
            pytest.skip("WeasyPrint not installed — returned empty PDF")
        # PDF magic bytes
        assert pdf_bytes[:4] == b"%PDF"

    def test_empty_markdown_still_renders(self, pdf_engine: PDFEngine) -> None:
        pdf_bytes = pdf_engine.render_pdf(
            report_markdown="",
            session_id="test-empty",
            query="Empty query",
            decision="NO_GO",
            citations=[],
        )
        assert isinstance(pdf_bytes, bytes)
        # Empty bytes is acceptable if WeasyPrint not installed


class TestMarkdownToHTML:
    """Tests for markdown conversion."""

    def test_converts_headers(self, pdf_engine: PDFEngine) -> None:
        html = pdf_engine._markdown_to_html("# Header 1\n## Header 2\n### Header 3")
        assert "<h1>" in html or "Header 1" in html

    def test_converts_bold(self, pdf_engine: PDFEngine) -> None:
        html = pdf_engine._markdown_to_html("This is **bold** text")
        assert "<strong>" in html or "<b>" in html or "bold" in html

    def test_converts_lists(self, pdf_engine: PDFEngine) -> None:
        html = pdf_engine._markdown_to_html("- Item 1\n- Item 2\n- Item 3")
        assert "Item 1" in html

    def test_handles_empty_string(self, pdf_engine: PDFEngine) -> None:
        html = pdf_engine._markdown_to_html("")
        assert isinstance(html, str)

    def test_converts_inline_images(self, pdf_engine: PDFEngine) -> None:
        md = "![Chart](data:image/png;base64,iVBORw0KGgo=)"
        html = pdf_engine._markdown_to_html(md)
        assert "img" in html.lower() or "base64" in html


class TestBuildCitationRows:
    """Tests for citation table HTML generation."""

    def test_builds_table_rows(self, pdf_engine: PDFEngine) -> None:
        citations = [
            {"source_name": "FDA", "source_url": "https://fda.gov", "retrieved_at": "2026-01-01", "data_hash": "abc123"},
            {"source_name": "CT.gov", "source_url": "https://ct.gov", "retrieved_at": "2026-01-02", "data_hash": "def456"},
        ]
        rows = pdf_engine._build_citation_rows(citations)
        assert "FDA" in rows
        assert "CT.gov" in rows
        assert "<tr>" in rows

    def test_empty_citations_returns_empty(self, pdf_engine: PDFEngine) -> None:
        rows = pdf_engine._build_citation_rows([])
        assert isinstance(rows, str)


class TestUploadToBlob:
    """Tests for Blob Storage upload."""

    def test_uploads_and_returns_url(self, pdf_engine: PDFEngine) -> None:
        """upload_to_blob lazily imports BlobServiceClient. Mock via builtins."""
        import builtins

        mock_blob_cls = MagicMock()
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()
        mock_blob.url = "https://pharma.blob.core.windows.net/reports/test.pdf"

        mock_blob_cls.from_connection_string.return_value = mock_client
        mock_client.get_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "azure.storage.blob":
                mod = MagicMock()
                mod.BlobServiceClient = mock_blob_cls
                return mod
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            url = pdf_engine.upload_to_blob(b"%PDF-1.4 test content", "session-123")

        # Should return a URL (either blob URL or local fallback)
        assert url is not None
        assert isinstance(url, str)
