"""
Unit tests for Clinical Retriever tools.

Tests ClinicalTrials.gov v2 API integration, FDA approvals,
and CDSCO web scraper with mock HTTP responses.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.retrievers.clinical.tools import (
    search_clinical_trials,
    search_fda_approvals,
    search_cdsco_drugs,
    _parse_cdsco_html,
    _cdsco_fallback,
)


class TestSearchClinicalTrials:
    """Tests for ClinicalTrials.gov v2 API."""

    @patch("src.agents.retrievers.clinical.tools.httpx.Client")
    def test_returns_trial_records(self, mock_client_class: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = '{"studies":[]}'
        mock_response.json.return_value = {
            "studies": [{
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT00000001", "briefTitle": "Test Trial"},
                    "statusModule": {
                        "overallStatus": "RECRUITING",
                        "startDateStruct": {"date": "2024-01-01"},
                        "completionDateStruct": {"date": "2026-12-31"},
                    },
                    "designModule": {
                        "phases": ["PHASE3"],
                        "enrollmentInfo": {"count": 500},
                    },
                    "sponsorCollaboratorsModule": {"leadSponsor": {"name": "TestPharma"}},
                    "conditionsModule": {"conditions": ["Melanoma"]},
                    "armsInterventionsModule": {"interventions": [{"name": "Pembrolizumab"}]},
                },
            }],
        }
        mock_response.url = "https://clinicaltrials.gov/api/v2/studies"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        trials, citation = search_clinical_trials("Pembrolizumab")

        assert len(trials) == 1
        assert trials[0]["nct_id"] == "NCT00000001"
        assert trials[0]["phase"] == "PHASE3"
        assert trials[0]["enrollment"] == 500
        assert citation.source_name == "ClinicalTrials.gov (v2 API)"


class TestSearchFDAApprovals:
    """Tests for FDA approval lookup."""

    @patch("src.agents.retrievers.clinical.tools.httpx.Client")
    def test_returns_approval_records(self, mock_client_class: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = '{"results":[]}'
        mock_response.json.return_value = {
            "results": [{
                "application_number": "BLA125514",
                "sponsor_name": "Merck",
                "submissions": [{
                    "submission_type": "ORIG",
                    "submission_status": "AP",
                    "submission_status_date": "20140904",
                    "review_priority": "PRIORITY",
                    "application_docs": [],
                }],
            }],
        }
        mock_response.url = "https://api.fda.gov/drug/drugsfda.json"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        approvals, citation = search_fda_approvals("pembrolizumab")
        assert len(approvals) == 1
        assert approvals[0]["review_priority"] == "PRIORITY"


class TestSearchCDSCO:
    """Tests for CDSCO web scraper."""

    @patch("src.agents.retrievers.clinical.tools.httpx.Client")
    def test_fallback_on_http_error(self, mock_client_class: MagicMock) -> None:
        import httpx
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_client_class.return_value = mock_client

        records, citation = search_cdsco_drugs("TestDrug")
        assert len(records) == 1
        assert records[0]["status"] == "DATA_UNAVAILABLE"
        assert "Fallback" in citation.source_name

    def test_cdsco_fallback(self) -> None:
        records, citation = _cdsco_fallback("TestDrug", "India")
        assert records[0]["data_source"] == "cdsco_fallback"
        assert "DATA_UNAVAILABLE" in records[0]["status"]


class TestParseCDSCOHTML:
    """Tests for CDSCO HTML parsing."""

    def test_parses_drug_table(self) -> None:
        html = """
        <html><body>
        <table class="table">
            <tr><th>Drug</th><th>Manufacturer</th><th>Approval No</th><th>Date</th><th>Status</th></tr>
            <tr><td>Paracetamol</td><td>Cipla</td><td>CT-2024-001</td><td>2024-03-15</td><td>Approved</td></tr>
        </table>
        </body></html>
        """
        results = _parse_cdsco_html(html, "Paracetamol", "India")
        assert len(results) == 1
        assert results[0]["drug_name"] == "Paracetamol"
        assert results[0]["manufacturer"] == "Cipla"

    def test_empty_html(self) -> None:
        results = _parse_cdsco_html("<html><body></body></html>", "X", "India")
        assert results == []
