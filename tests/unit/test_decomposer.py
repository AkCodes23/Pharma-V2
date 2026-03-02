"""
Unit tests for Planner Agent — IntentDecomposer.

Tests Azure OpenAI–based query decomposition into task DAGs
with mocked HTTP responses. Covers:
  - Happy path decomposition
  - Clarification request handling
  - Empty task edge case
  - Malformed JSON retry behavior
  - Pillar routing correctness
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.planner.decomposer import IntentDecomposer
from src.shared.models.enums import PillarType


@pytest.fixture
def decomposer() -> IntentDecomposer:
    """Create a decomposer with mocked settings."""
    with patch("src.agents.planner.decomposer.get_settings") as mock_settings:
        settings = MagicMock()
        settings.openai.endpoint = "https://test.openai.azure.com"
        settings.openai.api_key = "test-key"
        settings.openai.deployment_name = "gpt-4o"
        settings.openai.api_version = "2024-12-01-preview"
        mock_settings.return_value = settings
        d = IntentDecomposer()
    return d


def _mock_openai_response(content: dict) -> MagicMock:
    """Build a mock httpx response with given JSON content."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "choices": [{"message": {"content": json.dumps(content)}}],
    }
    response.raise_for_status = MagicMock()
    return response


class TestDecomposeHappyPath:
    """Tests for successful decomposition scenarios."""

    def test_returns_query_params_and_tasks(self, decomposer: IntentDecomposer) -> None:
        """Happy path: LLM returns well-formed task graph."""
        llm_response = {
            "needs_clarification": False,
            "clarification_question": None,
            "query_parameters": {
                "drug_name": "Pembrolizumab",
                "brand_name": "Keytruda",
                "target_market": "US",
                "time_horizon": "2027",
                "therapeutic_area": "Oncology",
            },
            "tasks": [
                {"pillar": "LEGAL", "description": "Patent landscape for Keytruda", "parameters": {"drug": "Keytruda"}},
                {"pillar": "CLINICAL", "description": "Clinical trials pipeline", "parameters": {"drug": "Keytruda"}},
                {"pillar": "COMMERCIAL", "description": "Revenue analysis", "parameters": {"drug": "Keytruda"}},
                {"pillar": "SOCIAL", "description": "Adverse events analysis", "parameters": {"drug": "Keytruda"}},
                {"pillar": "KNOWLEDGE", "description": "Internal knowledge base", "parameters": {"drug": "Keytruda"}},
            ],
        }
        with patch.object(decomposer, "_http_client") as mock_http:
            mock_http.post.return_value = _mock_openai_response(llm_response)
            params, tasks = decomposer.decompose("Analyze Keytruda market entry strategy", "session-123")

        assert params.drug_name == "Pembrolizumab"
        assert params.brand_name == "Keytruda"
        assert params.target_market == "US"
        assert len(tasks) == 5
        assert {t.pillar for t in tasks} == {
            PillarType.LEGAL, PillarType.CLINICAL, PillarType.COMMERCIAL,
            PillarType.SOCIAL, PillarType.KNOWLEDGE,
        }
        assert all(t.session_id == "session-123" for t in tasks)

    def test_tasks_have_unique_ids(self, decomposer: IntentDecomposer) -> None:
        """Each task should have a unique task_id."""
        llm_response = {
            "needs_clarification": False,
            "query_parameters": {"drug_name": "TestDrug"},
            "tasks": [
                {"pillar": "LEGAL", "description": "Legal task", "parameters": {}},
                {"pillar": "CLINICAL", "description": "Clinical task", "parameters": {}},
            ],
        }
        with patch.object(decomposer, "_http_client") as mock_http:
            mock_http.post.return_value = _mock_openai_response(llm_response)
            _, tasks = decomposer.decompose("Test query for drug analysis", "session-456")

        task_ids = [t.task_id for t in tasks]
        assert len(task_ids) == len(set(task_ids)), "Task IDs must be unique"


class TestDecomposeClarification:
    """Tests for clarification request handling."""

    def test_raises_value_error_on_clarification(self, decomposer: IntentDecomposer) -> None:
        """When LLM requests clarification, should raise ValueError."""
        llm_response = {
            "needs_clarification": True,
            "clarification_question": "Which specific drug formulation are you asking about?",
            "query_parameters": {},
            "tasks": [],
        }
        with patch.object(decomposer, "_http_client") as mock_http:
            mock_http.post.return_value = _mock_openai_response(llm_response)
            with pytest.raises(ValueError, match="clarification"):
                decomposer.decompose("Analyze the drug", "session-789")


class TestDecomposeEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_tasks_raises_value_error(self, decomposer: IntentDecomposer) -> None:
        """Decomposition producing zero tasks should raise ValueError."""
        llm_response = {
            "needs_clarification": False,
            "query_parameters": {"drug_name": "Unknown"},
            "tasks": [],
        }
        with patch.object(decomposer, "_http_client") as mock_http:
            mock_http.post.return_value = _mock_openai_response(llm_response)
            with pytest.raises(ValueError, match="zero tasks"):
                decomposer.decompose("Something very vague about drugs", "session-000")

    def test_malformed_json_triggers_retry(self, decomposer: IntentDecomposer) -> None:
        """Malformed JSON from LLM should trigger tenacity retry."""
        bad_response = MagicMock()
        bad_response.status_code = 200
        bad_response.json.return_value = {
            "choices": [{"message": {"content": "not valid json {{"}}],
        }
        bad_response.raise_for_status = MagicMock()

        good_response = _mock_openai_response({
            "needs_clarification": False,
            "query_parameters": {"drug_name": "Retry"},
            "tasks": [{"pillar": "LEGAL", "description": "Retried task", "parameters": {}}],
        })

        with patch.object(decomposer, "_http_client") as mock_http:
            mock_http.post.side_effect = [bad_response, good_response]
            # Disable tenacity wait for test speed
            decomposer.decompose.retry.wait = lambda *a, **k: 0  # type: ignore
            params, tasks = decomposer.decompose("Analyze retry drug scenario here", "session-retry")

        assert params.drug_name == "Retry"
        assert len(tasks) == 1

    def test_http_error_triggers_retry(self, decomposer: IntentDecomposer) -> None:
        """HTTP errors should trigger tenacity retry up to 3 attempts."""
        import httpx
        from tenacity import RetryError

        with patch.object(decomposer, "_http_client") as mock_http:
            mock_http.post.side_effect = httpx.HTTPError("Connection failed")
            decomposer.decompose.retry.wait = lambda *a, **k: 0  # type: ignore
            with pytest.raises(RetryError):
                decomposer.decompose("Should fail after retries for drug analysis", "session-fail")

        assert mock_http.post.call_count == 3  # 3 attempts

    def test_default_query_params_on_missing_fields(self, decomposer: IntentDecomposer) -> None:
        """Missing query_parameters fields should use defaults."""
        llm_response = {
            "needs_clarification": False,
            "query_parameters": {},
            "tasks": [{"pillar": "LEGAL", "description": "Task", "parameters": {}}],
        }
        with patch.object(decomposer, "_http_client") as mock_http:
            mock_http.post.return_value = _mock_openai_response(llm_response)
            params, _ = decomposer.decompose("Analyze a drug for market readiness", "session-defaults")

        assert params.drug_name == "Unknown"
        assert params.target_market == "Global"
        assert params.time_horizon == "2027"


class TestDecomposeClose:
    """Tests for resource cleanup."""

    def test_close_closes_http_client(self, decomposer: IntentDecomposer) -> None:
        with patch.object(decomposer, "_http_client") as mock_http:
            decomposer.close()
            mock_http.close.assert_called_once()
