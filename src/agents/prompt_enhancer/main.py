"""
Prompt enhancer service.
"""

from __future__ import annotations

import json
import logging
import os
from threading import Lock
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class PromptEnhancer:
    """LLM-based prompt enhancer for failed retriever tasks."""

    ENHANCEMENT_PROMPT = """You are a pharmaceutical intelligence prompt engineer.
A retriever agent produced low-quality results. Your task is to improve the original prompt
so the agent produces better results on retry.

ORIGINAL QUERY: {query}
PILLAR: {pillar}
ORIGINAL TASK DESCRIPTION: {task_description}

QUALITY EVALUATION FEEDBACK:
- Factual Accuracy: {factual_accuracy}
- Citation Completeness: {citation_completeness}
- Relevance: {relevance}
- Issues: {issues}
- Suggestions: {suggestions}

Generate an improved task description that addresses the quality issues.
Focus on:
1. Being more specific about what data to retrieve
2. Requiring explicit citations for every claim
3. Narrowing the scope if the original was too broad
4. Adding constraints to improve relevance

Respond in strict JSON:
{{
    "enhanced_description": "<improved task description>",
    "strategy_used": "<specificity|constraints|decompose|rephrase>",
    "changes_made": ["<change1>", "<change2>"]
}}"""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def enhance(
        self,
        query: str,
        pillar: str,
        task_description: str,
        quality_evaluation: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            from openai import AzureOpenAI

            client = AzureOpenAI(
                azure_endpoint=self._settings.azure_openai.endpoint,
                api_key=self._settings.azure_openai.api_key,
                api_version=self._settings.azure_openai.api_version,
            )

            prompt = self.ENHANCEMENT_PROMPT.format(
                query=query,
                pillar=pillar,
                task_description=task_description,
                factual_accuracy=quality_evaluation.get("factual_accuracy", "N/A"),
                citation_completeness=quality_evaluation.get("citation_completeness", "N/A"),
                relevance=quality_evaluation.get("relevance", "N/A"),
                issues=json.dumps(quality_evaluation.get("issues", [])),
                suggestions=json.dumps(quality_evaluation.get("suggestions", [])),
            )

            response = client.chat.completions.create(
                model=self._settings.azure_openai.deployment_name,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=800,
            )

            result = json.loads(response.choices[0].message.content)
            return {
                "enhanced_description": result.get("enhanced_description", task_description),
                "strategy_used": result.get("strategy_used", "unknown"),
                "changes_made": result.get("changes_made", []),
                "original_description": task_description,
            }
        except Exception:
            logger.exception("Prompt enhancement failed; using original description")
            return {
                "enhanced_description": task_description,
                "strategy_used": "fallback",
                "changes_made": [],
                "original_description": task_description,
            }


class EnhanceRequest(BaseModel):
    query: str = Field(..., min_length=1)
    pillar: str = Field(..., min_length=1)
    task_description: str = Field(..., min_length=1)
    quality_evaluation: dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="Pharma Agentic AI - Prompt Enhancer", version="0.1.0")
_enhancer: PromptEnhancer | None = None
_enhancer_lock = Lock()


def get_enhancer() -> PromptEnhancer:
    """Lazily initialize the enhancer so imports remain test-friendly."""
    global _enhancer
    if _enhancer is None:
        with _enhancer_lock:
            if _enhancer is None:
                _enhancer = PromptEnhancer()
    return _enhancer


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "prompt-enhancer"}


@app.post("/enhance")
async def enhance(request: EnhanceRequest) -> dict[str, Any]:
    return await get_enhancer().enhance(
        query=request.query,
        pillar=request.pillar,
        task_description=request.task_description,
        quality_evaluation=request.quality_evaluation,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
