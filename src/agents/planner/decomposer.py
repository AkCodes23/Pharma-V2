"""
Pharma Agentic AI — Planner Agent: Intent Decomposer.

Uses Azure OpenAI GPT-4o with Strict JSON Mode to decompose
a natural-language strategic query into a Directed Acyclic Graph
(DAG) of sub-tasks, each mapped to a specific strategic pillar.

Architecture context:
  - Service: Planner Agent
  - Responsibility: NL query → structured TaskGraph
  - Upstream: User via API Gateway
  - Downstream: Service Bus (via Publisher)
  - Failure: Returns error if decomposition fails after retries
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.shared.config import get_settings
from src.shared.models.enums import PillarType
from src.shared.models.schemas import QueryParameters, TaskNode

logger = logging.getLogger(__name__)

# ── System Prompt (Hardcoded — Context-Constrained) ─────────
DECOMPOSITION_SYSTEM_PROMPT = """You are the Planner Agent for a pharmaceutical strategic intelligence platform.

Your ONLY job is to decompose a user's strategic query into a structured task graph.

RULES:
1. You MUST output valid JSON matching the schema below. No other text.
2. Each task MUST map to exactly ONE pillar: LEGAL, CLINICAL, COMMERCIAL, SOCIAL, or KNOWLEDGE.
3. You MUST include at least one task per relevant pillar.
4. Task descriptions MUST be specific and actionable (include drug names, markets, dates).
5. Parameters MUST include all information needed for the retriever agent to execute.
6. If the query is ambiguous, request clarification by setting "needs_clarification" to true.
7. You MUST NOT invent data. You are ONLY decomposing the query.

OUTPUT SCHEMA:
{
  "needs_clarification": false,
  "clarification_question": null,
  "query_parameters": {
    "drug_name": "string",
    "brand_name": "string or null",
    "target_market": "string",
    "time_horizon": "string",
    "therapeutic_area": "string or null"
  },
  "tasks": [
    {
      "pillar": "LEGAL|CLINICAL|COMMERCIAL|SOCIAL|KNOWLEDGE",
      "description": "string",
      "parameters": {}
    }
  ]
}"""


class IntentDecomposer:
    """
    Decomposes natural-language pharma queries into task DAGs
    using Azure OpenAI with Strict JSON Mode.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._endpoint = settings.openai.endpoint.rstrip("/")
        self._api_key = settings.openai.api_key
        self._deployment = settings.openai.deployment_name
        self._api_version = settings.openai.api_version
        self._http_client = httpx.Client(timeout=60.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPError, json.JSONDecodeError)),
    )
    def decompose(
        self,
        query: str,
        session_id: str,
    ) -> tuple[QueryParameters, list[TaskNode]]:
        """
        Decompose a natural-language query into structured tasks.

        Args:
            query: The user's strategic query.
            session_id: The parent session ID for task creation.

        Returns:
            Tuple of (QueryParameters, list[TaskNode]).

        Raises:
            ValueError: If the LLM requests clarification.
            httpx.HTTPError: On persistent API failures.
        """
        url = (
            f"{self._endpoint}/openai/deployments/{self._deployment}"
            f"/chat/completions?api-version={self._api_version}"
        )

        response = self._http_client.post(
            url,
            headers={
                "Content-Type": "application/json",
                "api-key": self._api_key,
            },
            json={
                "messages": [
                    {"role": "system", "content": DECOMPOSITION_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                "temperature": 0.0,  # Deterministic output
                "response_format": {"type": "json_object"},
                "max_tokens": 2000,
            },
        )
        response.raise_for_status()

        result = response.json()
        content = result["choices"][0]["message"]["content"]
        parsed: dict[str, Any] = json.loads(content)

        logger.info(
            "Intent decomposition completed",
            extra={
                "session_id": session_id,
                "task_count": len(parsed.get("tasks", [])),
                "needs_clarification": parsed.get("needs_clarification", False),
            },
        )

        # Handle clarification requests
        if parsed.get("needs_clarification", False):
            raise ValueError(
                f"Query requires clarification: {parsed.get('clarification_question', 'Unknown')}"
            )

        # Parse query parameters
        qp_data = parsed.get("query_parameters", {})
        query_params = QueryParameters(
            drug_name=qp_data.get("drug_name", "Unknown"),
            brand_name=qp_data.get("brand_name"),
            target_market=qp_data.get("target_market", "Global"),
            time_horizon=qp_data.get("time_horizon", "2027"),
            therapeutic_area=qp_data.get("therapeutic_area"),
        )

        # Parse tasks
        tasks: list[TaskNode] = []
        for task_data in parsed.get("tasks", []):
            pillar = PillarType(task_data["pillar"])
            task = TaskNode(
                session_id=session_id,
                pillar=pillar,
                description=task_data["description"],
                parameters=task_data.get("parameters", {}),
            )
            tasks.append(task)

        if not tasks:
            raise ValueError("Decomposition produced zero tasks. Query may be too vague.")

        return query_params, tasks

    def close(self) -> None:
        """Close the HTTP client."""
        self._http_client.close()
