"""
Unit tests for Prompt Enhancer Agent.

Tests strategy classification (specificity, constraints, decompose, rephrase),
enhancement with mocked OpenAI, and fallback behavior.

The PromptEnhancer does a lazy `from openai import AzureOpenAI`
inside the enhance() method, so we mock via builtins.__import__.
"""

from __future__ import annotations

import builtins
import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.prompt_enhancer.main import PromptEnhancer


@pytest.fixture
def enhancer() -> PromptEnhancer:
    settings = MagicMock()
    settings.azure_openai = MagicMock()
    settings.azure_openai.endpoint = "https://test.openai.azure.com"
    settings.azure_openai.api_key = "test-key"
    settings.azure_openai.api_version = "2024-12-01-preview"
    settings.azure_openai.deployment_name = "gpt-4o"
    return PromptEnhancer(settings=settings)


def _mock_openai_for_response(response_dict: dict) -> MagicMock:
    """Create a mock AzureOpenAI class that returns given response."""
    mock_cls = MagicMock()
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(response_dict)
    mock_client.chat.completions.create.return_value = response
    return mock_cls


def _patch_openai_import(mock_cls: MagicMock):
    """Patch the lazy `from openai import AzureOpenAI` inside enhance()."""
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "openai":
            mod = MagicMock()
            mod.AzureOpenAI = mock_cls
            return mod
        return original_import(name, *args, **kwargs)

    return patch("builtins.__import__", side_effect=mock_import)


class TestEnhanceHappyPath:
    """Tests for successful prompt enhancement."""

    @pytest.mark.asyncio
    async def test_returns_enhanced_description(self, enhancer: PromptEnhancer) -> None:
        enhance_response = {
            "enhanced_description": "Search for Keytruda Phase 3 oncology trials with PFS/OS endpoints, cite NCT IDs.",
            "strategy_used": "specificity",
            "changes_made": ["Added trial phase", "Required NCT ID citations"],
        }
        mock_cls = _mock_openai_for_response(enhance_response)
        with _patch_openai_import(mock_cls):
            result = await enhancer.enhance(
                query="Analyze Keytruda",
                pillar="CLINICAL",
                task_description="Find clinical trials for Keytruda",
                quality_evaluation={
                    "factual_accuracy": 0.4,
                    "citation_completeness": 0.3,
                    "relevance": 0.8,
                    "issues": ["Insufficient citation"],
                    "suggestions": ["Add NCT IDs"],
                },
            )

        assert result["enhanced_description"] != "Find clinical trials for Keytruda"
        assert result["strategy_used"] == "specificity"
        assert len(result["changes_made"]) > 0
        assert result["original_description"] == "Find clinical trials for Keytruda"

    @pytest.mark.asyncio
    async def test_all_strategies(self, enhancer: PromptEnhancer) -> None:
        """All four strategies should be valid."""
        for strategy in ["specificity", "constraints", "decompose", "rephrase"]:
            enhance_response = {
                "enhanced_description": f"Enhanced with {strategy}",
                "strategy_used": strategy,
                "changes_made": [f"Applied {strategy}"],
            }
            mock_cls = _mock_openai_for_response(enhance_response)
            enhancer._client = None  # Reset cached client to use patched mock
            with _patch_openai_import(mock_cls):
                result = await enhancer.enhance("q", "LEGAL", "desc", {})
            assert result["strategy_used"] == strategy


class TestEnhanceFallback:
    """Tests for fallback behavior on enhancement failure."""

    @pytest.mark.asyncio
    async def test_failure_returns_original_description(self, enhancer: PromptEnhancer) -> None:
        """When OpenAI fails, should return original description as fallback."""
        original_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("openai not available")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=failing_import):
            result = await enhancer.enhance(
                query="q",
                pillar="LEGAL",
                task_description="Original task description",
                quality_evaluation={},
            )

        assert result["enhanced_description"] == "Original task description"
        assert result["strategy_used"] == "fallback"
        assert result["changes_made"] == []

    @pytest.mark.asyncio
    async def test_malformed_response_returns_fallback(self, enhancer: PromptEnhancer) -> None:
        """When LLM returns invalid JSON, should fallback."""
        mock_cls = MagicMock()
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "not valid json"
        mock_client.chat.completions.create.return_value = response

        with _patch_openai_import(mock_cls):
            result = await enhancer.enhance("q", "LEGAL", "Original", {})

        assert result["enhanced_description"] == "Original"
        assert result["strategy_used"] == "fallback"
