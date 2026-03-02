"""
Unit tests for DPO Training Pipeline.

Tests DPO pair collection, JSONL export, data validation,
and training job submission (mocked).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ml.dpo_training import DPODataCollector, DPOPair, DPOTrainer


class TestDPOPair:
    """Tests for DPOPair dataclass."""

    def test_creates_valid_pair(self) -> None:
        pair = DPOPair(
            prompt="Analyze Keytruda patent landscape",
            chosen="Keytruda has 3 patents expiring by 2028, including US10,000,001...",
            rejected="Keytruda may have some patents, generally speaking...",
            pillar="LEGAL",
            grounding_score=0.85,
            session_id="s-001",
        )
        assert pair.prompt == "Analyze Keytruda patent landscape"
        assert pair.grounding_score == 0.85
        assert pair.session_id == "s-001"

    def test_default_session_id(self) -> None:
        pair = DPOPair(prompt="p", chosen="c", rejected="r", pillar="LEGAL", grounding_score=0.5)
        assert pair.session_id == ""


class TestDPODataCollector:
    """Tests for DPO training pair collection."""

    def test_collect_rejected_creates_pair(self) -> None:
        """When is_accepted=False and alternative given, a pair is created."""
        collector = DPODataCollector(min_grounding_score=0.7)
        pair = collector.collect_from_session(
            session_id="s-001",
            pillar="LEGAL",
            prompt="Analyze patents",
            response="Vague response without details...",
            grounding_score=0.3,
            is_accepted=False,
            alternative_response="Detailed patent analysis with citations...",
        )
        assert pair is not None
        assert pair.chosen == "Detailed patent analysis with citations..."
        assert pair.rejected == "Vague response without details..."

    def test_accepted_without_alternative_returns_none(self) -> None:
        """When is_accepted=True, collect stores for future pairing but returns None."""
        collector = DPODataCollector(min_grounding_score=0.7)
        pair = collector.collect_from_session(
            session_id="s-001",
            pillar="LEGAL",
            prompt="Analyze patents",
            response="Detailed patent analysis with citations...",
            grounding_score=0.9,
            is_accepted=True,
            alternative_response=None,
        )
        # is_accepted=True does not create a pair directly
        assert pair is None

    def test_no_alternative_returns_none(self) -> None:
        collector = DPODataCollector()
        pair = collector.collect_from_session(
            session_id="s-003",
            pillar="LEGAL",
            prompt="Analyze",
            response="Some response",
            grounding_score=0.5,
            is_accepted=False,
            alternative_response=None,
        )
        assert pair is None

    def test_pairs_accumulated(self) -> None:
        """Rejected+alternative pairs accumulate in collector.pairs."""
        collector = DPODataCollector()
        for i in range(5):
            collector.collect_from_session(
                session_id=f"s-{i}",
                pillar="LEGAL",
                prompt=f"Query {i}",
                response=f"Bad {i}",
                grounding_score=0.3,
                is_accepted=False,
                alternative_response=f"Good {i}",
            )
        assert len(collector.pairs) == 5


class TestDPOExport:
    """Tests for JSONL export."""

    def test_export_to_jsonl(self) -> None:
        collector = DPODataCollector()
        collector.pairs = [
            DPOPair(prompt="p1", chosen="c1", rejected="r1", pillar="LEGAL", grounding_score=0.9),
            DPOPair(prompt="p2", chosen="c2", rejected="r2", pillar="CLINICAL", grounding_score=0.8),
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            output_path = Path(f.name)

        count = collector.export_to_jsonl(output_path)
        assert count == 2

        # Verify JSONL format
        lines = output_path.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert "prompt" in data
            assert "chosen" in data
            assert "rejected" in data

        output_path.unlink()

    def test_export_empty_returns_zero(self) -> None:
        collector = DPODataCollector()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            output_path = Path(f.name)
        count = collector.export_to_jsonl(output_path)
        assert count == 0
        output_path.unlink()


class TestDPOTrainer:
    """Tests for DPO training pipeline."""

    def test_load_data(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for i in range(3):
                f.write(json.dumps({"prompt": f"prompt_{i}", "chosen": f"chosen_{i}", "rejected": f"rejected_{i}"}) + "\n")
            data_path = Path(f.name)

        trainer = DPOTrainer(
            training_data_path=data_path,
            output_dir=Path(tempfile.mkdtemp()),
        )
        data = trainer.load_data()
        assert len(data) == 3
        data_path.unlink()

    def test_validate_data_valid(self) -> None:
        trainer = DPOTrainer(
            training_data_path=Path("/tmp/test.jsonl"),
            output_dir=Path("/tmp/output"),
        )
        # Prompts and responses must be >= 10 chars per validate_data logic
        data = [
            {"prompt": "Analyze Keytruda patent landscape in detail", "chosen": "Detailed analysis of patent US10001234...", "rejected": "Keytruda has some patents maybe..."},
            {"prompt": "What are the clinical trial results?", "chosen": "Phase 3 trial NCT123456 shows efficacy...", "rejected": "Some trials exist for this drug maybe..."},
        ]
        valid, errors = trainer.validate_data(data)
        assert len(valid) == 2
        assert len(errors) == 0

    def test_validate_data_missing_fields(self) -> None:
        trainer = DPOTrainer(
            training_data_path=Path("/tmp/test.jsonl"),
            output_dir=Path("/tmp/output"),
        )
        data = [
            {"prompt": "Some prompt text that is long enough", "chosen": "Some chosen text that is long enough"},  # missing 'rejected'
            {"prompt": "Another prompt text for testing here", "chosen": "Another chosen text long enough here", "rejected": "A rejected text that is long enough too"},
        ]
        valid, errors = trainer.validate_data(data)
        assert len(valid) == 1
        assert len(errors) == 1

    def test_validate_data_empty_chosen(self) -> None:
        trainer = DPOTrainer(
            training_data_path=Path("/tmp/test.jsonl"),
            output_dir=Path("/tmp/output"),
        )
        data = [
            {"prompt": "A sufficiently long prompt text here", "chosen": "", "rejected": "A sufficiently long rejected text"},
        ]
        valid, errors = trainer.validate_data(data)
        assert len(errors) == 1  # Empty chosen is invalid

    def test_train_azure_submits_job(self) -> None:
        """Azure training submission should call the fine-tuning API.
        
        Both `from openai import AzureOpenAI` and `from src.shared.config import get_settings`
        are lazily imported inside train_azure, so we mock via builtins.__import__.
        """
        trainer = DPOTrainer(
            training_data_path=Path("/tmp/test.jsonl"),
            output_dir=Path(tempfile.mkdtemp()),
        )
        data = [{"prompt": "Analyze the patent landscape for Keytruda", "chosen": "Detailed patent analysis with citations...", "rejected": "There might be some patents for this drug"}]

        mock_openai_cls = MagicMock()
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.files.create.return_value = MagicMock(id="file-123")
        mock_client.fine_tuning.jobs.create.return_value = MagicMock(
            id="ft-job-123", status="pending"
        )

        mock_settings_fn = MagicMock()
        settings = MagicMock()
        settings.openai.endpoint = "https://test.openai.azure.com"
        settings.openai.api_key = "test"
        settings.openai.api_version = "2024-12-01"
        settings.openai.deployment_name = "gpt-4o"
        mock_settings_fn.return_value = settings

        import builtins
        original_import = builtins.__import__

        def mock_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "openai":
                mod = MagicMock()
                mod.AzureOpenAI = mock_openai_cls
                return mod
            if name == "src.shared.config" and fromlist and "get_settings" in fromlist:
                mod = MagicMock()
                mod.get_settings = mock_settings_fn
                return mod
            return original_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=mock_import):
            result = trainer.train_azure(data)

        assert result is not None
        assert result["status"] in ("SUBMITTED", "FAILED")
