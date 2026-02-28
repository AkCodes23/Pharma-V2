"""
Pharma Agentic AI — RLHF/DPO Training Data Collector.

Extracts training pairs from the reflection_log table for
fine-tuning local Small Language Models (SLMs) to replicate
the Quality Evaluator's behavior without expensive GPT-4o calls.

Architecture context:
  - Service: ML Pipeline (offline, scheduled via Celery Beat)
  - Responsibility: Curate (prompt, chosen, rejected) DPO pairs
  - Upstream: PostgreSQL reflection_log, session data
  - Downstream: Training script (trl DPO trainer)
  - Schedule: Weekly batch extraction

Data format (DPO):
  {
    "prompt": "Evaluate the grounding of this clinical analysis...",
    "chosen": <response with grounding_score >= 0.9>,
    "rejected": <response with grounding_score < 0.6>
  }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.shared.config import get_settings

logger = logging.getLogger(__name__)

# Minimum sessions required before training is viable
MIN_TRAINING_PAIRS = 100
# Thresholds for DPO pair curation
CHOSEN_THRESHOLD = 0.9    # High-quality responses
REJECTED_THRESHOLD = 0.6  # Low-quality responses (for contrast)


class DPODataCollector:
    """
    Collects and curates DPO training pairs from production data.

    Pipeline:
      1. Query reflection_log for sessions with grounding scores
      2. Pair "chosen" (score >= 0.9) with "rejected" (score < 0.6)
      3. Format as DPO training dataset
      4. Export to JSONL file for trl trainer
    """

    def __init__(self) -> None:
        self._pool = None

    async def _get_pool(self):
        """Lazy-init the connection pool."""
        if self._pool is None:
            import asyncpg
            settings = get_settings()
            self._pool = await asyncpg.create_pool(settings.postgres.url, min_size=2, max_size=5)
        return self._pool

    async def collect_training_pairs(self) -> list[dict[str, Any]]:
        """
        Extract DPO training pairs from reflection_log.

        Returns:
            List of {prompt, chosen, rejected} dicts.
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # Get high-quality evaluations (chosen)
            chosen_rows = await conn.fetch(
                """
                SELECT session_id, checks, overall_score, created_at
                FROM reflection_log
                WHERE overall_score >= $1
                ORDER BY created_at DESC
                LIMIT 500
                """,
                CHOSEN_THRESHOLD,
            )

            # Get low-quality evaluations (rejected)
            rejected_rows = await conn.fetch(
                """
                SELECT session_id, checks, overall_score, created_at
                FROM reflection_log
                WHERE overall_score < $1
                ORDER BY created_at DESC
                LIMIT 500
                """,
                REJECTED_THRESHOLD,
            )

        if len(chosen_rows) < 10 or len(rejected_rows) < 10:
            logger.warning(
                "Insufficient training data",
                extra={"chosen": len(chosen_rows), "rejected": len(rejected_rows)},
            )
            return []

        # Pair chosen and rejected responses
        pairs = []
        for chosen, rejected in zip(chosen_rows, rejected_rows):
            chosen_checks = json.loads(chosen["checks"]) if isinstance(chosen["checks"], str) else chosen["checks"]
            rejected_checks = json.loads(rejected["checks"]) if isinstance(rejected["checks"], str) else rejected["checks"]

            pair = {
                "prompt": self._build_evaluation_prompt(chosen_checks),
                "chosen": json.dumps({
                    "score": float(chosen["overall_score"]),
                    "checks": chosen_checks,
                    "verdict": "PASS",
                }),
                "rejected": json.dumps({
                    "score": float(rejected["overall_score"]),
                    "checks": rejected_checks,
                    "verdict": "FAIL",
                }),
                "metadata": {
                    "chosen_session": chosen["session_id"],
                    "rejected_session": rejected["session_id"],
                    "chosen_score": float(chosen["overall_score"]),
                    "rejected_score": float(rejected["overall_score"]),
                },
            }
            pairs.append(pair)

        logger.info("Collected DPO training pairs", extra={"count": len(pairs)})
        return pairs

    async def export_to_jsonl(self, output_path: str = "/tmp/pharma_dpo_training.jsonl") -> str:
        """
        Export training pairs to JSONL file for trl DPO trainer.

        Returns:
            Path to the exported JSONL file.
        """
        pairs = await self.collect_training_pairs()

        if len(pairs) < MIN_TRAINING_PAIRS:
            logger.warning(
                f"Only {len(pairs)} pairs — minimum {MIN_TRAINING_PAIRS} required for training",
            )

        path = Path(output_path)
        with path.open("w", encoding="utf-8") as f:
            for pair in pairs:
                f.write(json.dumps(pair, default=str) + "\n")

        logger.info("Training data exported", extra={"path": str(path), "pairs": len(pairs)})
        return str(path)

    def _build_evaluation_prompt(self, checks: dict[str, Any]) -> str:
        """
        Reconstruct the evaluation prompt from check data.

        This is the prompt that the Quality Evaluator originally
        received — we're training the local model to replicate
        its scoring behavior.
        """
        return (
            "You are a pharmaceutical research quality evaluator. "
            "Score the following agent response on factual accuracy, "
            "citation completeness, and relevance to the original query. "
            f"Checks performed: {json.dumps(list(checks.keys()))}. "
            "Return a JSON object with 'score' (0.0-1.0) and 'verdict' (PASS/FAIL)."
        )

    async def check_training_readiness(self) -> dict[str, Any]:
        """
        Check if there's enough data for a training run.

        Returns:
            Readiness report with counts and recommendation.
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM reflection_log")
            chosen = await conn.fetchval(
                "SELECT COUNT(*) FROM reflection_log WHERE overall_score >= $1",
                CHOSEN_THRESHOLD,
            )
            rejected = await conn.fetchval(
                "SELECT COUNT(*) FROM reflection_log WHERE overall_score < $1",
                REJECTED_THRESHOLD,
            )

        ready = min(chosen, rejected) >= MIN_TRAINING_PAIRS
        return {
            "total_reflections": total,
            "chosen_count": chosen,
            "rejected_count": rejected,
            "viable_pairs": min(chosen, rejected),
            "minimum_required": MIN_TRAINING_PAIRS,
            "ready_for_training": ready,
            "recommendation": (
                "Ready for DPO fine-tuning" if ready
                else f"Need {MIN_TRAINING_PAIRS - min(chosen, rejected)} more pairs"
            ),
        }
