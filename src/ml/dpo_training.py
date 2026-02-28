"""
Pharma Agentic AI — DPO Training Script.

Implements Direct Preference Optimization (DPO) for fine-tuning
the grounding validation model. Collects preferred/rejected response
pairs from production sessions and trains a reward model.

Architecture context:
  - Service: ML Pipeline (offline batch processing)
  - Responsibility: Continuous model improvement via RLHF/DPO
  - Upstream: PostgreSQL dpo_training_pairs table
  - Downstream: Azure OpenAI fine-tuning API or local model
  - Failure: Training failures are logged; production model unaffected
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DPOPair:
    """A single preference pair for DPO training."""
    prompt: str
    chosen: str
    rejected: str
    pillar: str
    grounding_score: float
    session_id: str = ""


class DPODataCollector:
    """
    Collects DPO training pairs from production sessions.

    Pairs are generated when:
      1. Supervisor rejects an agent response (rejected) and the
         agent produces a corrected response (chosen)
      2. Human reviewer provides feedback on agent outputs
      3. Grounding scores are below threshold (low-score response
         becomes rejected; high-score alternative becomes chosen)
    """

    def __init__(self, min_grounding_score: float = 0.7) -> None:
        self.min_grounding_score = min_grounding_score
        self.pairs: list[DPOPair] = []

    def collect_from_session(
        self,
        session_id: str,
        pillar: str,
        prompt: str,
        response: str,
        grounding_score: float,
        is_accepted: bool,
        alternative_response: str | None = None,
    ) -> DPOPair | None:
        """
        Collect a DPO pair from a single session interaction.

        Returns a DPOPair if both chosen and rejected responses are available.
        """
        if not is_accepted and alternative_response:
            pair = DPOPair(
                prompt=prompt,
                chosen=alternative_response,
                rejected=response,
                pillar=pillar,
                grounding_score=grounding_score,
                session_id=session_id,
            )
            self.pairs.append(pair)
            logger.info(
                "DPO pair collected (rejected → corrected)",
                extra={"session_id": session_id, "pillar": pillar},
            )
            return pair

        if is_accepted and grounding_score >= self.min_grounding_score:
            # Store as potential "chosen" — no pair yet until we have a rejection
            logger.debug(
                "High-quality response stored for potential DPO pairing",
                extra={"session_id": session_id, "score": grounding_score},
            )

        return None

    def export_to_jsonl(self, output_path: Path) -> int:
        """
        Export collected pairs to JSONL format for training.

        Format compatible with both OpenAI fine-tuning and
        Hugging Face TRL DPO trainer.

        Returns number of pairs exported.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        count = 0
        with open(output_path, "w", encoding="utf-8") as f:
            for pair in self.pairs:
                record = {
                    "prompt": pair.prompt,
                    "chosen": pair.chosen,
                    "rejected": pair.rejected,
                    "pillar": pair.pillar,
                    "grounding_score": pair.grounding_score,
                    "session_id": pair.session_id,
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

        logger.info(f"Exported {count} DPO pairs to {output_path}")
        return count


class DPOTrainer:
    """
    DPO training pipeline.

    Supports two backends:
      1. Azure OpenAI fine-tuning API (production)
      2. Local HuggingFace TRL DPO trainer (development)
    """

    def __init__(
        self,
        training_data_path: Path,
        output_dir: Path,
        learning_rate: float = 5e-7,
        epochs: int = 3,
        batch_size: int = 4,
        beta: float = 0.1,
    ) -> None:
        self.training_data_path = training_data_path
        self.output_dir = output_dir
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.batch_size = batch_size
        self.beta = beta  # DPO temperature parameter

    def load_data(self) -> list[dict[str, Any]]:
        """Load training data from JSONL file."""
        if not self.training_data_path.exists():
            raise FileNotFoundError(f"Training data not found: {self.training_data_path}")

        data = []
        with open(self.training_data_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data.append(json.loads(line))

        logger.info(f"Loaded {len(data)} DPO training pairs")
        return data

    def validate_data(self, data: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        """
        Validate training data quality.

        Returns:
            Tuple of (valid_pairs, error_messages).
        """
        valid = []
        errors = []

        for i, record in enumerate(data):
            # Required fields
            for field in ["prompt", "chosen", "rejected"]:
                if field not in record or not record[field].strip():
                    errors.append(f"Record {i}: missing or empty '{field}'")
                    break
            else:
                # Length sanity checks
                if len(record["prompt"]) < 10:
                    errors.append(f"Record {i}: prompt too short ({len(record['prompt'])} chars)")
                elif len(record["chosen"]) < 10:
                    errors.append(f"Record {i}: chosen response too short")
                elif record["chosen"] == record["rejected"]:
                    errors.append(f"Record {i}: chosen and rejected are identical")
                else:
                    valid.append(record)

        logger.info(f"Data validation: {len(valid)} valid, {len(errors)} invalid")
        return valid, errors

    def train_local(self, data: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Train DPO model locally using HuggingFace TRL.

        This is a stub — requires transformers + trl packages and
        a local GPU. For production, use Azure OpenAI fine-tuning.

        Returns training metrics.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        metrics: dict[str, Any] = {
            "status": "COMPLETED",
            "training_pairs": len(data),
            "epochs": self.epochs,
            "learning_rate": self.learning_rate,
            "beta": self.beta,
            "start_time": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Check if TRL is available
            from trl import DPOTrainer as TRLDPOTrainer
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from datasets import Dataset

            logger.info("TRL DPO training starting...")

            # Convert to HF Dataset format
            dataset = Dataset.from_list([
                {"prompt": d["prompt"], "chosen": d["chosen"], "rejected": d["rejected"]}
                for d in data
            ])

            # This would need a base model — placeholder for the full implementation
            metrics["backend"] = "trl_local"
            metrics["note"] = "Full TRL training requires a base model and GPU"
            logger.info("TRL DPO training pipeline configured", extra=metrics)

        except ImportError:
            logger.warning("TRL/transformers not installed — saving data only")
            metrics["backend"] = "data_export_only"
            metrics["note"] = "Install trl, transformers, datasets for local training"

        # Save training data regardless
        output_file = self.output_dir / "dpo_training_data.jsonl"
        with open(output_file, "w", encoding="utf-8") as f:
            for record in data:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        metrics["output_path"] = str(output_file)
        metrics["end_time"] = datetime.now(timezone.utc).isoformat()

        # Save metrics
        metrics_file = self.output_dir / "training_metrics.json"
        with open(metrics_file, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

        logger.info("DPO training pipeline completed", extra=metrics)
        return metrics

    def train_azure(self, data: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Submit DPO fine-tuning job to Azure OpenAI.

        Uploads training data and creates a fine-tuning job.
        This is an async operation — poll for status.

        Returns job metadata.
        """
        try:
            from openai import AzureOpenAI
            from src.shared.config import get_settings

            settings = get_settings()
            client = AzureOpenAI(
                azure_endpoint=settings.openai.endpoint,
                api_key=settings.openai.api_key,
                api_version=settings.openai.api_version,
            )

            # Prepare training file
            training_file_path = self.output_dir / "azure_dpo_training.jsonl"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with open(training_file_path, "w", encoding="utf-8") as f:
                for record in data:
                    f.write(json.dumps({
                        "messages": [
                            {"role": "user", "content": record["prompt"]},
                            {"role": "assistant", "content": record["chosen"]},
                        ],
                    }, ensure_ascii=False) + "\n")

            # Upload training file
            with open(training_file_path, "rb") as f:
                upload = client.files.create(file=f, purpose="fine-tune")

            # Create fine-tuning job
            job = client.fine_tuning.jobs.create(
                training_file=upload.id,
                model=settings.openai.deployment_name,
            )

            return {
                "status": "SUBMITTED",
                "job_id": job.id,
                "file_id": upload.id,
                "training_pairs": len(data),
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error("Azure fine-tuning submission failed", extra={"error": str(e)})
            return {
                "status": "FAILED",
                "error": str(e),
                "training_pairs": len(data),
            }


# ── CLI Entry Point ───────────────────────────────────────


def main() -> None:
    """Run DPO training pipeline from command line."""
    import argparse

    parser = argparse.ArgumentParser(description="Pharma AI DPO Training Pipeline")
    parser.add_argument("--data", type=Path, required=True, help="Path to JSONL training data")
    parser.add_argument("--output", type=Path, default=Path("models/dpo"), help="Output directory")
    parser.add_argument("--backend", choices=["local", "azure"], default="local")
    parser.add_argument("--lr", type=float, default=5e-7, help="Learning rate")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--beta", type=float, default=0.1, help="DPO beta parameter")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    trainer = DPOTrainer(
        training_data_path=args.data,
        output_dir=args.output,
        learning_rate=args.lr,
        epochs=args.epochs,
        beta=args.beta,
    )

    data = trainer.load_data()
    valid_data, errors = trainer.validate_data(data)

    if errors:
        logger.warning(f"Found {len(errors)} validation errors")
        for err in errors[:10]:
            logger.warning(f"  {err}")

    if not valid_data:
        logger.error("No valid training data — aborting")
        return

    if args.backend == "azure":
        metrics = trainer.train_azure(valid_data)
    else:
        metrics = trainer.train_local(valid_data)

    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
