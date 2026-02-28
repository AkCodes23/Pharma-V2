"""
Unit tests for Legal Retriever tools.

Tests the Orange Book API integration, patent exclusivity search,
and IPO web scraper with mock HTTP responses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.agents.retrievers.legal.tools import (
    search_orange_book,
    search_patent_exclusivity,
    search_ipo_patents,
    _parse_ipo_html,
    _ipo_estimation_fallback,
)


class TestSearchOrangeBook:
    """Tests for the FDA Orange Book search via openFDA."""

    @patch("src.agents.retrievers.legal.tools.httpx.Client")
    def test_returns_patents_and_citation(self, mock_client_class: MagicMock) -> None:
        """Happy path: API returns results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"results":[]}'
        mock_response.json.return_value = {
            "results": [{
                "application_number": "NDA123456",
                "products": [{
                    "brand_name": "TestDrug",
                    "dosage_form": "TABLET",
                    "route": "ORAL",
                    "te_code": "AB",
                    "active_ingredients": [{"name": "TestIngredient"}],
                }],
            }],
        }
        mock_response.url = "https://api.fda.gov/drug/drugsfda.json?search=test"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        patents, citation = search_orange_book("TestIngredient")

        assert len(patents) == 1
        assert patents[0]["application_number"] == "NDA123456"
        assert citation.source_name == "FDA Orange Book (openFDA API)"
        assert citation.data_hash  # SHA-256 must be non-empty

    @patch("src.agents.retrievers.legal.tools.httpx.Client")
    def test_empty_results(self, mock_client_class: MagicMock) -> None:
        """No matches returns empty list."""
        mock_response = MagicMock()
        mock_response.text = '{"results":[]}'
        mock_response.json.return_value = {"results": []}
        mock_response.url = "https://api.fda.gov/test"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        patents, citation = search_orange_book("NonexistentDrug")
        assert patents == []
        assert "0 records" in citation.excerpt


class TestSearchPatentExclusivity:
    """Tests for patent exclusivity data retrieval."""

    @patch("src.agents.retrievers.legal.tools.httpx.Client")
    def test_returns_exclusivity_records(self, mock_client_class: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = '{"results":[]}'
        mock_response.json.return_value = {
            "results": [{
                "application_number": "NDA123",
                "submissions": [{
                    "submission_type": "ORIG",
                    "submission_status": "AP",
                    "application_docs": [{"type": "Letter", "date": "2020-01-01"}],
                }],
            }],
        }
        mock_response.url = "https://api.fda.gov/test"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        records, citation = search_patent_exclusivity("TestDrug")
        assert len(records) == 1
        assert records[0]["submission_status"] == "AP"
        assert citation.source_name == "FDA Drug Exclusivity (openFDA API)"


class TestSearchIPOPatents:
    """Tests for IPO web scraper."""

    @patch("src.agents.retrievers.legal.tools.httpx.Client")
    def test_fallback_on_http_error(self, mock_client_class: MagicMock) -> None:
        """Should return fallback record on HTTP failure."""
        import httpx
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_client_class.return_value = mock_client

        patents, citation = search_ipo_patents("TestDrug")
        assert len(patents) == 1
        assert patents[0]["status"] == "DATA_UNAVAILABLE"
        assert "Fallback" in citation.source_name


class TestParseIPOHTML:
    """Tests for IPO HTML parsing."""

    def test_parses_table_rows(self) -> None:
        html = """
        <html><body>
        <table class="table">
            <tr><th>App No</th><th>Title</th><th>Applicant</th><th>Date</th><th>Status</th></tr>
            <tr><td>IN001</td><td>Method for synthesis</td><td>Pharma Corp</td><td>2024-01-01</td><td>Granted</td></tr>
        </table>
        </body></html>
        """
        results = _parse_ipo_html(html, "TestDrug", "India")
        assert len(results) == 1
        assert results[0]["application_number"] == "IN001"
        assert results[0]["status"] == "Granted"

    def test_empty_html_returns_empty(self) -> None:
        results = _parse_ipo_html("<html><body></body></html>", "TestDrug", "India")
        assert results == []


class TestIPOEstimationFallback:
    """Tests for IPO fallback."""

    def test_returns_data_unavailable(self) -> None:
        records, citation = _ipo_estimation_fallback("TestDrug", "India")
        assert len(records) == 1
        assert records[0]["status"] == "DATA_UNAVAILABLE"
        assert records[0]["data_source"] == "ipo_fallback"
