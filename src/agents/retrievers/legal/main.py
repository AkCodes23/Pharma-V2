"""
Pharma Agentic AI — Legal Retriever Agent.

Specialized retriever for the LEGAL pillar. Searches patent
databases (USPTO Orange Book, Indian Patent Office) to determine
patent expiry dates, blocking patents, and legal runway.

Architecture context:
  - Service: Legal Retriever (Azure Container App, KEDA-scaled)
  - Responsibility: Patent and exclusivity data retrieval
  - Data sources: FDA Orange Book (openFDA), Indian Patent Office
  - Data ownership: Patent status, expiry dates, exclusivity periods
"""

from __future__ import annotations

from typing import Any

from src.shared.models.enums import AgentType, PillarType
from src.shared.models.schemas import Citation, TaskNode

from src.agents.retrievers.base_retriever import BaseRetriever
from src.agents.retrievers.legal.tools import (
    search_ipo_patents,
    search_orange_book,
    search_patent_exclusivity,
)


class LegalRetriever(BaseRetriever):
    """Legal pillar retriever — patent and exclusivity analysis."""

    @property
    def agent_type(self) -> AgentType:
        return AgentType.LEGAL_RETRIEVER

    @property
    def pillar(self) -> PillarType:
        return PillarType.LEGAL

    def execute_tools(self, task: TaskNode) -> tuple[dict[str, Any], list[Citation]]:
        """
        Execute patent search tools.

        Searches:
          1. FDA Orange Book for US patent data
          2. Patent exclusivity records
          3. Indian Patent Office for India-specific patents
        """
        ingredient = task.parameters.get("drug_name", task.parameters.get("ingredient", ""))
        brand_name = task.parameters.get("brand_name")
        target_market = task.parameters.get("target_market", "US")

        findings: dict[str, Any] = {
            "drug_name": ingredient,
            "target_market": target_market,
            "orange_book_results": [],
            "exclusivity_results": [],
            "regional_patents": [],
            "blocking_patents": [],
            "earliest_generic_entry": None,
        }
        citations: list[Citation] = []

        # 1. FDA Orange Book search
        try:
            patents, ob_citation = search_orange_book(ingredient, brand_name)
            findings["orange_book_results"] = patents
            citations.append(ob_citation)
        except Exception as e:
            findings["orange_book_error"] = str(e)

        # 2. Patent exclusivity search
        try:
            exclusivities, exc_citation = search_patent_exclusivity(ingredient)
            findings["exclusivity_results"] = exclusivities
            citations.append(exc_citation)
        except Exception as e:
            findings["exclusivity_error"] = str(e)

        # 3. Regional patent search (if target market is India)
        if target_market.lower() in ("india", "in"):
            try:
                regional_patents, ipo_citation = search_ipo_patents(ingredient, target_market)
                findings["regional_patents"] = regional_patents
                citations.append(ipo_citation)

                # Identify blocking patents
                for patent in regional_patents:
                    if patent.get("status") == "Active":
                        findings["blocking_patents"].append({
                            "patent_number": patent["patent_number"],
                            "expiry_date": patent["expiry_date"],
                            "patent_type": patent.get("patent_type", "Unknown"),
                        })
            except Exception as e:
                findings["regional_patent_error"] = str(e)

        # Compute earliest generic entry date
        all_expiry_dates = []
        for bp in findings.get("blocking_patents", []):
            if bp.get("expiry_date"):
                all_expiry_dates.append(bp["expiry_date"])
        if all_expiry_dates:
            findings["earliest_generic_entry"] = max(all_expiry_dates)

        return findings, citations
