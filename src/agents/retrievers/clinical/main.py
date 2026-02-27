"""
Pharma Agentic AI — Clinical Retriever Agent.

Retrieves clinical trial data to assess competitive saturation
and pipeline readiness for a target drug/market combination.
"""

from __future__ import annotations

from typing import Any

from src.shared.models.enums import AgentType, PillarType
from src.shared.models.schemas import Citation, TaskNode

from src.agents.retrievers.base_retriever import BaseRetriever
from src.agents.retrievers.clinical.tools import search_clinical_trials, search_cdsco


class ClinicalRetriever(BaseRetriever):
    """Clinical pillar retriever — trial pipeline analysis."""

    @property
    def agent_type(self) -> AgentType:
        return AgentType.CLINICAL_RETRIEVER

    @property
    def pillar(self) -> PillarType:
        return PillarType.CLINICAL

    def execute_tools(self, task: TaskNode) -> tuple[dict[str, Any], list[Citation]]:
        """Search clinical trial databases for the target drug/market."""
        drug_name = task.parameters.get("drug_name", "")
        therapeutic_area = task.parameters.get("therapeutic_area", "")
        target_market = task.parameters.get("target_market", "")

        findings: dict[str, Any] = {
            "drug_name": drug_name,
            "target_market": target_market,
            "active_trials": [],
            "phase3_trials": [],
            "cdsco_applications": [],
            "competitive_saturation": "LOW",
            "total_active_trial_count": 0,
        }
        citations: list[Citation] = []

        # 1. Search ClinicalTrials.gov for active trials
        try:
            trials, ct_citation = search_clinical_trials(
                intervention=drug_name,
                condition=therapeutic_area or None,
                status="RECRUITING",
            )
            findings["active_trials"] = trials
            findings["total_active_trial_count"] = len(trials)
            citations.append(ct_citation)
        except Exception as e:
            findings["clinical_trials_error"] = str(e)

        # 2. Search for Phase III specifically
        try:
            phase3, p3_citation = search_clinical_trials(
                intervention=drug_name,
                phase="PHASE3",
            )
            findings["phase3_trials"] = phase3
            citations.append(p3_citation)
        except Exception as e:
            findings["phase3_error"] = str(e)

        # 3. CDSCO search if India market
        if target_market.lower() in ("india", "in"):
            try:
                cdsco_data, cdsco_citation = search_cdsco(drug_name, target_market)
                findings["cdsco_applications"] = cdsco_data
                citations.append(cdsco_citation)
            except Exception as e:
                findings["cdsco_error"] = str(e)

        # 4. Compute competitive saturation level
        trial_count = findings["total_active_trial_count"]
        if trial_count >= 10:
            findings["competitive_saturation"] = "HIGH"
        elif trial_count >= 5:
            findings["competitive_saturation"] = "MEDIUM"
        else:
            findings["competitive_saturation"] = "LOW"

        return findings, citations
