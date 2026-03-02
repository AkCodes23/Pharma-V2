"""
Pharma Agentic AI - Social/Regulatory Retriever Agent.

Retrieves adverse event data and computes safety risk scores.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.shared.models.enums import AgentType, PillarType
from src.shared.models.schemas import Citation, TaskNode

from src.agents.retrievers.base_retriever import BaseRetriever
from src.agents.retrievers.runtime import create_retriever_app, run_retriever_service
from src.agents.retrievers.social.tools import compute_safety_score, search_faers

if TYPE_CHECKING:
    from src.shared.infra.audit import AuditService
    from src.shared.infra.cosmos_client import CosmosDBClient


class SocialRetriever(BaseRetriever):
    """Social/Regulatory pillar retriever - safety signal analysis."""

    def __init__(
        self,
        cosmos: CosmosDBClient,
        audit: AuditService,
        subscription_name: str = "retriever-social-sub",
    ) -> None:
        super().__init__(cosmos=cosmos, audit=audit, subscription_name=subscription_name)

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


app = create_retriever_app(
    SocialRetriever,
    agent_name="retriever-social",
    default_subscription="retriever-social-sub",
)


if __name__ == "__main__":
    run_retriever_service(app)
