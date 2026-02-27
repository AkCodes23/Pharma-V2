"""
Pharma Agentic AI — Social/Regulatory Retriever Agent.

Retrieves adverse event data and computes safety risk scores.
"""

from __future__ import annotations

from typing import Any

from src.shared.models.enums import AgentType, PillarType
from src.shared.models.schemas import Citation, TaskNode

from src.agents.retrievers.base_retriever import BaseRetriever
from src.agents.retrievers.social.tools import compute_safety_score, search_faers


class SocialRetriever(BaseRetriever):
    """Social/Regulatory pillar retriever — safety signal analysis."""

    @property
    def agent_type(self) -> AgentType:
        return AgentType.SOCIAL_RETRIEVER

    @property
    def pillar(self) -> PillarType:
        return PillarType.SOCIAL

    def execute_tools(self, task: TaskNode) -> tuple[dict[str, Any], list[Citation]]:
        drug_name = task.parameters.get("drug_name", "")

        findings: dict[str, Any] = {
            "drug_name": drug_name,
            "adverse_events": [],
            "safety_score": {},
            "regulatory_risk": "LOW",
        }
        citations: list[Citation] = []

        # 1. Search FAERS
        try:
            events, faers_cit = search_faers(drug_name)
            findings["adverse_events"] = events
            citations.append(faers_cit)

            # 2. Compute safety score (deterministic, no LLM)
            findings["safety_score"] = compute_safety_score(events)
            findings["regulatory_risk"] = findings["safety_score"].get("risk_level", "LOW")
        except Exception as e:
            findings["faers_error"] = str(e)

        return findings, citations
