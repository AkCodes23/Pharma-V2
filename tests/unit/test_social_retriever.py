"""
Unit tests for Social Retriever tools.

Tests FAERS API, PubMed E-utilities, safety scoring,
and composite sentiment aggregation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.retrievers.social.tools import (
    search_faers,
    search_pubmed_safety,
    compute_safety_score,
    aggregate_sentiment,
    _risk_recommendation,
)


class TestSearchFAERS:
    """Tests for FDA FAERS API integration."""

    @patch("src.agents.retrievers.social.tools.httpx.Client")
    def test_returns_adverse_events(self, mock_client_class: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = '{"results":[]}'
        mock_response.json.return_value = {
            "results": [{
                "safetyreportid": "RPT-001",
                "receivedate": "20250101",
                "serious": 1,
                "seriousnessdeath": 0,
                "seriousnesshospitalization": 1,
                "patient": {
                    "reaction": [{"reactionmeddrapt": "Nausea"}],
                    "drug": [{"drugcharacterization": "1"}],
                    "patientsex": "2",
                    "patientonsetage": "65",
                },
                "occurcountry": "US",
            }],
        }
        mock_response.url = "https://api.fda.gov/drug/event.json"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        events, citation = search_faers("TestDrug")

        assert len(events) == 1
        assert events[0]["report_id"] == "RPT-001"
        assert events[0]["serious"] == 1
        assert "Nausea" in events[0]["reactions"]
        assert citation.source_name == "FDA FAERS (openFDA API)"


class TestComputeSafetyScore:
    """Tests for deterministic safety scoring."""

    def test_empty_events_returns_low(self) -> None:
        score = compute_safety_score([])
        assert score["risk_level"] == "LOW"
        assert score["total_events"] == 0

    def test_high_serious_rate(self) -> None:
        events = [{"serious": 1, "seriousness_death": 0, "seriousness_hospitalization": 1, "reactions": ["Pain"]}] * 30
        events += [{"serious": 0, "seriousness_death": 0, "seriousness_hospitalization": 0, "reactions": []}] * 10
        score = compute_safety_score(events)
        assert score["risk_level"] == "HIGH"  # 75% serious
        assert score["serious_pct"] == 75.0

    def test_critical_death_rate(self) -> None:
        events = [{"serious": 1, "seriousness_death": 1, "seriousness_hospitalization": 0, "reactions": []}] * 10
        events += [{"serious": 0, "seriousness_death": 0, "seriousness_hospitalization": 0, "reactions": []}] * 10
        score = compute_safety_score(events)
        assert score["risk_level"] == "CRITICAL"  # 50% death

    def test_top_reactions_ranked(self) -> None:
        events = [
            {"serious": 0, "seriousness_death": 0, "seriousness_hospitalization": 0, "reactions": ["Nausea", "Fatigue"]},
            {"serious": 0, "seriousness_death": 0, "seriousness_hospitalization": 0, "reactions": ["Nausea"]},
            {"serious": 0, "seriousness_death": 0, "seriousness_hospitalization": 0, "reactions": ["Headache"]},
        ]
        score = compute_safety_score(events)
        top = score["top_reactions"]
        assert top[0]["reaction"] == "Nausea"
        assert top[0]["count"] == 2


class TestSearchPubMedSafety:
    """Tests for PubMed E-utilities integration."""

    @patch("src.agents.retrievers.social.tools.httpx.Client")
    def test_returns_articles(self, mock_client_class: MagicMock) -> None:
        # Mock two sequential HTTP calls (search + summary)
        search_response = MagicMock()
        search_response.json.return_value = {
            "esearchresult": {"idlist": ["12345678"]},
        }
        search_response.raise_for_status = MagicMock()

        summary_response = MagicMock()
        summary_response.text = '{"result":{}}'
        summary_response.json.return_value = {
            "result": {
                "uids": ["12345678"],
                "12345678": {
                    "title": "Safety Profile of TestDrug",
                    "authors": [{"name": "Smith J"}],
                    "source": "J Clin Oncol",
                    "pubdate": "2025 Jan",
                    "pubtype": ["Journal Article"],
                },
            },
        }
        summary_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = [search_response, summary_response]
        mock_client_class.return_value = mock_client

        articles, citation = search_pubmed_safety("TestDrug")

        assert len(articles) == 1
        assert articles[0]["pmid"] == "12345678"
        assert articles[0]["first_author"] == "Smith J"
        assert citation.source_name == "PubMed (NCBI E-utilities)"


class TestAggregateSentiment:
    """Tests for composite sentiment aggregation."""

    def test_critical_composite(self) -> None:
        safety = {"risk_level": "CRITICAL", "total_events": 100, "serious_pct": 60.0}
        articles = [{}] * 25  # HIGH_SCRUTINY

        result = aggregate_sentiment(safety, articles)
        assert result["composite_risk_level"] == "CRITICAL"
        assert result["literature_signal"] == "HIGH_SCRUTINY"

    def test_low_risk_limited_data(self) -> None:
        safety = {"risk_level": "LOW", "total_events": 5, "serious_pct": 5.0}
        articles = [{}] * 1

        result = aggregate_sentiment(safety, articles)
        assert result["composite_risk_level"] == "LOW"
        assert result["literature_signal"] == "LIMITED_DATA"

    def test_medium_elevated_by_scrutiny(self) -> None:
        safety = {"risk_level": "MEDIUM", "total_events": 50, "serious_pct": 15.0}
        articles = [{}] * 25

        result = aggregate_sentiment(safety, articles)
        assert result["composite_risk_level"] == "HIGH"


class TestRiskRecommendation:
    """Tests for risk-to-recommendation mapping."""

    def test_all_levels_have_recommendations(self) -> None:
        for level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            rec = _risk_recommendation(level)
            assert len(rec) > 10  # Non-trivial recommendation
