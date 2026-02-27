"""
Pharma Agentic AI — Prompt Enhancer Agent.

A2A sub-agent that improves failed prompts when a retriever agent's
result quality score is below the threshold. Takes the original
prompt + quality evaluation feedback and generates an improved prompt.

Architecture context:
  - Service: Prompt Enhancer (A2A sub-agent)
  - Responsibility: Prompt refinement for retry attempts
  - Upstream: Quality Evaluator (on quality failure)
  - Downstream: Original Retriever Agent (re-dispatched task)
  - LLM: Azure OpenAI GPT-4o for prompt improvement
  - Failure: If enhancement fails, use original prompt for retry
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class PromptEnhancer:
    """
    LLM-based prompt enhancer for failed retriever tasks.

    When a retriever agent's result fails quality evaluation,
    this agent analyzes the failure reasons and generates an
    improved, more specific prompt for the retry attempt.

    Strategies:
      1. Add specificity: Narrow the search scope
      2. Add constraints: Require specific citation types
      3. Decompose: Break complex queries into simpler sub-queries
      4. Rephrase: Fix ambiguous or vague language
    """

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
        """
        Generate an improved prompt for a failed retriever task.

        Args:
            query: Original user query.
            pillar: Agent pillar type.
            task_description: Original task description that failed.
            quality_evaluation: Quality evaluation result.

        Returns:
            Dict with enhanced_description, strategy_used, and changes_made.
        """
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

            logger.info(
                "Prompt enhanced",
                extra={
                    "pillar": pillar,
                    "strategy": result.get("strategy_used", "unknown"),
                    "changes": len(result.get("changes_made", [])),
                },
            )

            return {
                "enhanced_description": result.get("enhanced_description", task_description),
                "strategy_used": result.get("strategy_used", "unknown"),
                "changes_made": result.get("changes_made", []),
                "original_description": task_description,
            }

        except Exception:
            logger.exception("Prompt enhancement failed — using original description")
            return {
                "enhanced_description": task_description,
                "strategy_used": "fallback",
                "changes_made": [],
                "original_description": task_description,
            }
