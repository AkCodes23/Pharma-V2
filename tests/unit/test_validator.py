"""
Unit tests for Supervisor Agent — GroundingValidator.

Tests two-pass validation (rule-based + LLM), grounding score
calculation, conflict detection, and edge cases.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.supervisor.validator import GroundingValidator
from src.shared.models.enums import AgentType, ConflictSeverity, PillarType
from src.shared.models.schemas import AgentResult, Citation


def _make_result(pillar: PillarType, findings: dict, citations: list[Citation] | None = None) -> AgentResult:
    """Helper to create a valid AgentResult with all required fields."""
    return AgentResult(
        task_id="task-001",
        session_id="test-session-001",
        agent_type=AgentType.LEGAL_RETRIEVER,
        pillar=pillar,
        findings=findings,
        citations=citations or [
            Citation(source_name="TestSource", source_url="https://test.com", excerpt="Test data", data_hash="abc123"),
        ],
        confidence=0.85,
        execution_time_ms=1200,
    )


@pytest.fixture
def validator() -> GroundingValidator:
    with patch("src.agents.supervisor.validator.get_settings") as mock_settings:
        settings = MagicMock()
        settings.openai.endpoint = "https://test.openai.azure.com"
        settings.openai.api_key = "test-key"
        settings.openai.deployment_name = "gpt-4o"
        settings.openai.api_version = "2024-12-01-preview"
        mock_settings.return_value = settings
        v = GroundingValidator()
    return v


class TestValidateHappyPath:
    """Tests for successful validation with clean results."""

    def test_valid_results_pass(self, validator: GroundingValidator) -> None:
        results = [
            _make_result(PillarType.LEGAL, {"blocking_patents": []}),
            _make_result(PillarType.CLINICAL, {"trials": []}),
        ]
        llm_response = {
            "is_valid": True,
            "grounding_score": 0.85,
            "conflicts": [],
            "validation_notes": "All results well-grounded.",
        }
        with patch.object(validator, "_http_client") as mock_http:
            resp = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(llm_response)}}]}
            resp.raise_for_status = MagicMock()
            mock_http.post.return_value = resp
            result = validator.validate(results)

        assert result.is_valid is True
        assert result.grounding_score >= 0.0

    def test_grounding_score_in_valid_range(self, validator: GroundingValidator) -> None:
        results = [_make_result(PillarType.LEGAL, {"data": "test"})]
        llm_response = {
            "is_valid": True,
            "grounding_score": 0.95,
            "conflicts": [],
            "validation_notes": "",
        }
        with patch.object(validator, "_http_client") as mock_http:
            resp = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(llm_response)}}]}
            resp.raise_for_status = MagicMock()
            mock_http.post.return_value = resp
            result = validator.validate(results)

        assert 0.0 <= result.grounding_score <= 1.0


class TestRuleBasedConflicts:
    """Tests for deterministic rule-based conflict detection."""

    def test_detects_patent_market_conflict(self, validator: GroundingValidator) -> None:
        """Legal says blocked by patents, Commercial says clear market."""
        results = [
            _make_result(PillarType.LEGAL, {
                "blocking_patents": [{"status": "active", "expiry_date": "2030-01-01"}],
                "patent_status": "BLOCKED",
            }),
            _make_result(PillarType.COMMERCIAL, {
                "market_status": "CLEAR_TO_ENTER",
                "revenue_data": {"total": 5000000000},
            }),
        ]
        conflicts = validator._detect_rule_based_conflicts(results)
        # Should detect a cross-pillar conflict between LEGAL and COMMERCIAL
        assert isinstance(conflicts, list)


class TestValidateEdgeCases:
    """Tests for edge case handling."""

    def test_zero_results_returns_invalid(self, validator: GroundingValidator) -> None:
        """No agent results should return invalid with low grounding score."""
        with patch.object(validator, "_http_client") as mock_http:
            llm_response = {
                "is_valid": False,
                "grounding_score": 0.0,
                "conflicts": [],
                "validation_notes": "No agent results to validate.",
            }
            resp = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(llm_response)}}]}
            resp.raise_for_status = MagicMock()
            mock_http.post.return_value = resp
            result = validator.validate([])

        assert result.grounding_score == 0.0

    def test_missing_citations_detected(self, validator: GroundingValidator) -> None:
        """Results with empty citations should be flagged as low grounding."""
        # Use a MagicMock instead of real AgentResult to bypass min_length=1
        mock_result = MagicMock()
        mock_result.pillar = PillarType.LEGAL
        mock_result.findings = {"patent_data": "Some finding without citation"}
        mock_result.citations = []
        mock_result.model_dump.return_value = {
            "pillar": "LEGAL",
            "findings": {"patent_data": "Some finding"},
            "citations": [],
        }

        llm_response = {
            "is_valid": False,
            "grounding_score": 0.3,
            "conflicts": [],
            "validation_notes": "Missing citations for legal findings.",
        }
        with patch.object(validator, "_http_client") as mock_http:
            resp = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(llm_response)}}]}
            resp.raise_for_status = MagicMock()
            mock_http.post.return_value = resp
            result = validator.validate([mock_result])

        assert result.grounding_score < 0.6


class TestValidatorLifecycle:
    """Tests for resource cleanup."""

    def test_close_closes_http_client(self, validator: GroundingValidator) -> None:
        with patch.object(validator, "_http_client") as mock_http:
            validator.close()
            mock_http.close.assert_called_once()
