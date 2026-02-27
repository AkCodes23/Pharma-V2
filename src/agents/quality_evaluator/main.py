"""
Pharma Agentic AI — Quality Evaluator Agent.

A2A sub-agent that evaluates the quality of retriever agent results
before they reach the Supervisor. Scores factual accuracy, citation
completeness, and relevance using an LLM-based rubric.

Architecture context:
  - Service: Quality Evaluator (A2A sub-agent)
  - Responsibility: Pre-validation quality scoring
  - Upstream: Retriever agents (via A2A DELEGATE)
  - Downstream: Supervisor Agent (if quality passes), Prompt Enhancer (if fails)
  - LLM: Azure OpenAI GPT-4o for evaluation
  - Failure: If scoring fails, pass the result through unscored
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class QualityEvaluator:
    """
    LLM-based quality evaluator for agent results.

    Scoring dimensions:
      1. Factual accuracy (0-1): Are claims supported by citations?
      2. Citation completeness (0-1): Are all data points cited?
      3. Relevance (0-1): Is the result relevant to the query?

    Overall score = weighted average (accuracy: 0.5, citation: 0.3, relevance: 0.2)

    If overall score < 0.6, the result is rejected and sent to
    the Prompt Enhancer for re-prompting.
    """

    QUALITY_THRESHOLD = 0.6

    EVALUATION_PROMPT = """You are a pharmaceutical intelligence quality evaluator.
Evaluate the following agent result for factual accuracy, citation completeness, and relevance.

QUERY: {query}
PILLAR: {pillar}
RESULT:
{result_json}

Score each dimension from 0.0 to 1.0:
1. factual_accuracy: Are all factual claims supported by the provided citations?
2. citation_completeness: Does every data point have a corresponding citation?
3. relevance: Is the result directly relevant to the user's query?

Respond in strict JSON:
{{
    "factual_accuracy": <float>,
    "citation_completeness": <float>,
    "relevance": <float>,
    "issues": ["<issue1>", "<issue2>"],
    "suggestions": ["<suggestion1>"]
}}"""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def evaluate(
        self,
        query: str,
        pillar: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Evaluate an agent result's quality.

        Args:
            query: Original user query.
            pillar: Agent pillar type.
            result: Agent result dict (findings + citations).

        Returns:
            Evaluation dict with scores, overall_score, pass/fail,
            issues, and suggestions.
        """
        try:
            from openai import AzureOpenAI

            client = AzureOpenAI(
                azure_endpoint=self._settings.azure_openai.endpoint,
                api_key=self._settings.azure_openai.api_key,
                api_version=self._settings.azure_openai.api_version,
            )

            prompt = self.EVALUATION_PROMPT.format(
                query=query,
                pillar=pillar,
                result_json=json.dumps(result, indent=2, default=str)[:4000],
            )

            response = client.chat.completions.create(
                model=self._settings.azure_openai.deployment_name,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=500,
            )

            scores = json.loads(response.choices[0].message.content)

            # Compute weighted overall score
            overall = (
                scores.get("factual_accuracy", 0.0) * 0.5
                + scores.get("citation_completeness", 0.0) * 0.3
                + scores.get("relevance", 0.0) * 0.2
            )

            evaluation = {
                "factual_accuracy": scores.get("factual_accuracy", 0.0),
                "citation_completeness": scores.get("citation_completeness", 0.0),
                "relevance": scores.get("relevance", 0.0),
                "overall_score": round(overall, 3),
                "passed": overall >= self.QUALITY_THRESHOLD,
                "issues": scores.get("issues", []),
                "suggestions": scores.get("suggestions", []),
            }

            logger.info(
                "Quality evaluation complete",
                extra={
                    "pillar": pillar,
                    "overall_score": overall,
                    "passed": evaluation["passed"],
                },
            )

            return evaluation

        except Exception:
            logger.exception("Quality evaluation failed — passing result through")
            return {
                "factual_accuracy": None,
                "citation_completeness": None,
                "relevance": None,
                "overall_score": None,
                "passed": True,  # Fail-open: don't block pipeline on evaluator failure
                "issues": ["Quality evaluation unavailable"],
                "suggestions": [],
            }
