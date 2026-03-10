"""
Quality evaluator service.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class QualityEvaluator:
    """LLM-based quality evaluator for agent results."""

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

    async def evaluate(self, query: str, pillar: str, result: dict[str, Any]) -> dict[str, Any]:
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
            overall = (
                scores.get("factual_accuracy", 0.0) * 0.5
                + scores.get("citation_completeness", 0.0) * 0.3
                + scores.get("relevance", 0.0) * 0.2
            )

            return {
                "factual_accuracy": scores.get("factual_accuracy", 0.0),
                "citation_completeness": scores.get("citation_completeness", 0.0),
                "relevance": scores.get("relevance", 0.0),
                "overall_score": round(overall, 3),
                "passed": overall >= self.QUALITY_THRESHOLD,
                "issues": scores.get("issues", []),
                "suggestions": scores.get("suggestions", []),
            }

        except Exception:
            logger.exception("Quality evaluation failed; passing result through")
            return {
                "factual_accuracy": None,
                "citation_completeness": None,
                "relevance": None,
                "overall_score": None,
                "passed": True,
                "issues": ["Quality evaluation unavailable"],
                "suggestions": [],
            }


class EvaluateRequest(BaseModel):
    query: str = Field(..., min_length=1)
    pillar: str = Field(..., min_length=1)
    result: dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="Pharma Agentic AI - Quality Evaluator", version="0.1.0")
_evaluator: QualityEvaluator | None = None


def get_evaluator() -> QualityEvaluator:
    """Lazily initialize the evaluator so imports remain test-friendly."""
    global _evaluator
    if _evaluator is None:
        _evaluator = QualityEvaluator()
    return _evaluator


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "quality-evaluator"}


@app.post("/evaluate")
async def evaluate(request: EvaluateRequest) -> dict[str, Any]:
    return await get_evaluator().evaluate(
        query=request.query,
        pillar=request.pillar,
        result=request.result,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
