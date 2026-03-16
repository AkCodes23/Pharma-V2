"""
Unit tests for Quality Evaluator Agent.

Tests scoring dimensions (accuracy, citation, relevance),
weighted overall score calculation, pass/fail threshold,
and fail-open behavior.

The QualityEvaluator does a lazy `from openai import AzureOpenAI`
inside the evaluate() method, so we mock via builtins.__import__.
"""

from __future__ import annotations

import builtins
import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.quality_evaluator.main import QualityEvaluator


@pytest.fixture
def evaluator() -> QualityEvaluator:
    settings = MagicMock()
    settings.azure_openai = MagicMock()
    settings.azure_openai.endpoint = "https://test.openai.azure.com"
    settings.azure_openai.api_key = "test-key"
    settings.azure_openai.api_version = "2024-12-01-preview"
    settings.azure_openai.deployment_name = "gpt-4o"
    return QualityEvaluator(settings=settings)


def _mock_openai_for_scores(scores_response: dict) -> MagicMock:
    """Create a mock AzureOpenAI class that returns given scores."""
    mock_cls = MagicMock()
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(scores_response)
    mock_client.chat.completions.create.return_value = response
    return mock_cls


def _patch_openai_import(mock_cls: MagicMock):
    """Patch the lazy `from openai import AzureOpenAI` inside evaluate()."""
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "openai":
            mod = MagicMock()
            mod.AzureOpenAI = mock_cls
            return mod
        return original_import(name, *args, **kwargs)

    return patch("builtins.__import__", side_effect=mock_import)


class TestEvaluateScoring:
    """Tests for scoring calculation."""

    @pytest.mark.asyncio
    async def test_weighted_overall_score(self, evaluator: QualityEvaluator) -> None:
        scores_response = {
            "factual_accuracy": 0.9,
            "citation_completeness": 0.8,
            "relevance": 0.7,
            "issues": [],
            "suggestions": [],
        }
        mock_cls = _mock_openai_for_scores(scores_response)
        with _patch_openai_import(mock_cls):
            result = await evaluator.evaluate(
                query="Test query",
                pillar="LEGAL",
                result={"findings": "test"},
            )

        expected = 0.9 * 0.5 + 0.8 * 0.3 + 0.7 * 0.2
        assert abs(result["overall_score"] - round(expected, 3)) < 0.01
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_below_threshold_fails(self, evaluator: QualityEvaluator) -> None:
        scores_response = {
            "factual_accuracy": 0.3,
            "citation_completeness": 0.2,
            "relevance": 0.1,
            "issues": ["Low accuracy", "Missing citations"],
            "suggestions": ["Add citations"],
        }
        mock_cls = _mock_openai_for_scores(scores_response)
        with _patch_openai_import(mock_cls):
            result = await evaluator.evaluate("q", "LEGAL", {"data": "test"})

        assert result["passed"] is False
        assert result["overall_score"] < QualityEvaluator.QUALITY_THRESHOLD

    @pytest.mark.asyncio
    async def test_threshold_boundary(self, evaluator: QualityEvaluator) -> None:
        """Score exactly at threshold should pass."""
        # 0.6 * 0.5 + 0.6 * 0.3 + 0.6 * 0.2 = 0.6
        scores_response = {
            "factual_accuracy": 0.6,
            "citation_completeness": 0.6,
            "relevance": 0.6,
            "issues": [],
            "suggestions": [],
        }
        mock_cls = _mock_openai_for_scores(scores_response)
        with _patch_openai_import(mock_cls):
            result = await evaluator.evaluate("q", "LEGAL", {"data": "test"})

        assert result["passed"] is True


class TestFailOpen:
    """Tests for fail-open behavior on evaluator failure."""

    @pytest.mark.asyncio
    async def test_exception_returns_pass_through(self, evaluator: QualityEvaluator) -> None:
        """If the evaluator itself fails, should pass through (fail-open)."""
        original_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("openai not available")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=failing_import):
            result = await evaluator.evaluate("q", "LEGAL", {"data": "test"})

        assert result["passed"] is True  # Fail-open
        assert result["overall_score"] is None

    @pytest.mark.asyncio
    async def test_api_error_returns_pass_through(self, evaluator: QualityEvaluator) -> None:
        """API failure should fail open."""
        mock_cls = MagicMock()
        mock_cls.side_effect = ConnectionError("Service unavailable")
        with _patch_openai_import(mock_cls):
            result = await evaluator.evaluate("q", "LEGAL", {"data": "test"})

        assert result["passed"] is True


class TestEvaluateOutput:
    """Tests for output format consistency."""

    @pytest.mark.asyncio
    async def test_output_has_all_keys(self, evaluator: QualityEvaluator) -> None:
        scores_response = {
            "factual_accuracy": 0.8,
            "citation_completeness": 0.7,
            "relevance": 0.9,
            "issues": [],
            "suggestions": ["Consider adding more data"],
        }
        mock_cls = _mock_openai_for_scores(scores_response)
        with _patch_openai_import(mock_cls):
            result = await evaluator.evaluate("q", "LEGAL", {"data": "test"})

        expected_keys = {"factual_accuracy", "citation_completeness", "relevance", "overall_score", "passed", "issues", "suggestions"}
        assert expected_keys.issubset(set(result.keys()))
