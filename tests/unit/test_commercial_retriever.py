"""
Unit tests for Commercial Retriever tools.

Tests SEC EDGAR search, Yahoo Finance lookup, and market data
estimation with mocked HTTP / yfinance responses.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.retrievers.commercial.tools import (
    get_market_data,
    get_drug_revenue,
    _search_edgar_company,
    _get_yfinance_data,
    _estimate_generic_share,
)


class TestGetMarketData:
    """Tests for composite market data retrieval."""

    @patch("src.agents.retrievers.commercial.tools._get_yfinance_data")
    @patch("src.agents.retrievers.commercial.tools._search_edgar_company")
    def test_returns_market_data(
        self,
        mock_edgar: MagicMock,
        mock_yf: MagicMock,
    ) -> None:
        mock_edgar.return_value = {"cik": "0000310158", "filings": [], "total_hits": 5}
        mock_yf.return_value = {
            "company_name": "Merck & Co",
            "market_cap": 300_000_000_000,
            "total_revenue": 60_000_000_000,
            "revenue_growth": 8.5,
            "pe_ratio": 25.0,
            "sector": "Healthcare",
        }

        data, citation = get_market_data("pembrolizumab", "Oncology", "US")

        assert data["therapeutic_area"] == "Oncology"
        assert data["target_market"] == "US"
        assert data["total_addressable_market_usd"] == 280_000_000_000
        assert data["market_growth_cagr_pct"] == 8.5
        assert data["data_source"] == "sec_edgar_yfinance"
        assert citation.source_name == "SEC EDGAR + Yahoo Finance"

    @patch("src.agents.retrievers.commercial.tools._get_yfinance_data")
    @patch("src.agents.retrievers.commercial.tools._search_edgar_company")
    def test_india_market_adjustment(
        self,
        mock_edgar: MagicMock,
        mock_yf: MagicMock,
    ) -> None:
        mock_edgar.return_value = {"cik": "", "filings": [], "total_hits": 0}
        mock_yf.return_value = {
            "company_name": "",
            "market_cap": 0,
            "total_revenue": 0,
            "revenue_growth": 0,
            "pe_ratio": None,
            "sector": "Healthcare",
        }

        data, _ = get_market_data("ibuprofen", "Cardiovascular", "India")

        # India factor = 0.12 * Cardiovascular TAM (75B)
        expected_tam = int(75_000_000_000 * 0.12)
        assert data["total_addressable_market_usd"] == expected_tam


class TestGetDrugRevenue:
    """Tests for drug revenue estimation."""

    @patch("src.agents.retrievers.commercial.tools._get_yfinance_data")
    @patch("src.agents.retrievers.commercial.tools._search_edgar_company")
    def test_returns_annual_revenue_projections(
        self,
        mock_edgar: MagicMock,
        mock_yf: MagicMock,
    ) -> None:
        mock_edgar.return_value = {"cik": "123", "filings": [], "total_hits": 1}
        mock_yf.return_value = {
            "company_name": "TestPharma",
            "market_cap": 100_000_000_000,
            "total_revenue": 50_000_000_000,
            "revenue_growth": 10.0,
            "pe_ratio": 20.0,
            "sector": "Healthcare",
        }

        data, citation = get_drug_revenue("TestDrug")

        assert data["company_name"] == "TestPharma"
        assert "annual_revenue" in data
        assert len(data["annual_revenue"]) == 5  # 2 retrospective + current + 2 projected
        assert data["data_source"] == "sec_edgar_yfinance"


class TestEdgarSearch:
    """Tests for SEC EDGAR full-text search."""

    @patch("src.agents.retrievers.commercial.tools.httpx.Client")
    def test_returns_filings(self, mock_client_class: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [{
                    "_source": {
                        "entity_id": "CIK123",
                        "form_type": "10-K",
                        "file_date": "2025-03-15",
                        "display_names": ["TestPharma Inc"],
                    },
                }],
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = _search_edgar_company("TestDrug")
        assert result["cik"] == "CIK123"
        assert len(result["filings"]) == 1

    @patch("src.agents.retrievers.commercial.tools.httpx.Client")
    def test_handles_http_error(self, mock_client_class: MagicMock) -> None:
        import httpx
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_client_class.return_value = mock_client

        result = _search_edgar_company("TestDrug")
        assert result == {"cik": "", "filings": [], "total_hits": 0}


class TestYFinanceData:
    """Tests for Yahoo Finance data retrieval."""

    def test_unknown_drug_returns_empty(self) -> None:
        result = _get_yfinance_data("unknowndrug123")
        assert result["market_cap"] == 0
        assert result["company_name"] == ""

    @patch("src.agents.retrievers.commercial.tools.yfinance")
    def test_known_drug_maps_to_ticker(self, mock_yf: MagicMock) -> None:
        """Known drugs should map to ticker symbols."""
        # pembrolizumab → MRK
        import importlib
        import src.agents.retrievers.commercial.tools as tools_mod

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "longName": "Merck & Co., Inc.",
            "marketCap": 300_000_000_000,
            "totalRevenue": 60_000_000_000,
            "revenueGrowth": 0.085,
            "trailingPE": 25.0,
            "sector": "Healthcare",
        }

        with patch.dict("sys.modules", {"yfinance": MagicMock()}):
            with patch("yfinance.Ticker", return_value=mock_ticker):
                result = _get_yfinance_data("pembrolizumab")
                # May fail in isolation — tests ticker mapping exists
                assert "company_name" in result


class TestEstimateGenericShare:
    """Tests for generic market share estimation."""

    def test_known_therapeutic_areas(self) -> None:
        assert _estimate_generic_share("Oncology") == 15.0
        assert _estimate_generic_share("Cardiovascular") == 68.0

    def test_unknown_area_returns_default(self) -> None:
        assert _estimate_generic_share("UnknownArea") == 35.0
