"""
Pharma Agentic AI - Commercial Retriever Agent.

Retrieves market intelligence data for the COMMERCIAL pillar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.shared.models.enums import AgentType, PillarType
from src.shared.models.schemas import Citation, TaskNode

from src.agents.retrievers.base_retriever import BaseRetriever
from src.agents.retrievers.runtime import create_retriever_app, run_retriever_service
from src.agents.retrievers.commercial.tools import get_drug_revenue, get_market_data

if TYPE_CHECKING:
    from src.shared.infra.audit import AuditService
    from src.shared.infra.cosmos_client import CosmosDBClient


class CommercialRetriever(BaseRetriever):
    """Commercial pillar retriever - market and revenue analysis."""

    def __init__(
        self,
        cosmos: CosmosDBClient,
        audit: AuditService,
        subscription_name: str = "retriever-commercial-sub",
    ) -> None:
        super().__init__(cosmos=cosmos, audit=audit, subscription_name=subscription_name)

    @property
    def agent_type(self) -> AgentType:
        return AgentType.COMMERCIAL_RETRIEVER

    @property
    def pillar(self) -> PillarType:
        return PillarType.COMMERCIAL

    def execute_tools(self, task: TaskNode) -> tuple[dict[str, Any], list[Citation]]:
        drug_name = task.parameters.get("drug_name", "")
        therapeutic_area = task.parameters.get("therapeutic_area", "")
        target_market = task.parameters.get("target_market", "")

        findings: dict[str, Any] = {
            "drug_name": drug_name,
            "target_market": target_market,
            "market_data": {},
            "revenue_data": {},
            "market_attractiveness": "MEDIUM",
        }
        citations: list[Citation] = []

        # 1. Market size and growth
        try:
            market, m_cit = get_market_data(drug_name, therapeutic_area, target_market)
            findings["market_data"] = market
            citations.append(m_cit)
        except Exception as e:
            findings["market_data_error"] = str(e)

        # 2. Revenue data
        try:
            revenue, r_cit = get_drug_revenue(drug_name)
            findings["revenue_data"] = revenue
            citations.append(r_cit)
        except Exception as e:
            findings["revenue_error"] = str(e)

        # 3. Compute market attractiveness
        tam = findings.get("market_data", {}).get("total_addressable_market_usd", 0)
        cagr = findings.get("market_data", {}).get("market_growth_cagr_pct", 0)
        if tam > 1_000_000_000 and cagr > 10:
            findings["market_attractiveness"] = "HIGH"
        elif tam > 500_000_000 and cagr > 5:
            findings["market_attractiveness"] = "MEDIUM"
        else:
            findings["market_attractiveness"] = "LOW"

        return findings, citations


app = create_retriever_app(
    CommercialRetriever,
    agent_name="retriever-commercial",
    default_subscription="retriever-commercial-sub",
)


if __name__ == "__main__":
    run_retriever_service(app)
