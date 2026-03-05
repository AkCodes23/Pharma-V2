"""
Pharma Agentic AI - Clinical Retriever Agent.

Retrieves clinical trial data to assess competitive saturation
and pipeline readiness for a target drug/market combination.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.shared.models.enums import AgentType, PillarType
from src.shared.models.schemas import Citation, TaskNode

from src.agents.retrievers.base_retriever import BaseRetriever
from src.agents.retrievers.runtime import create_retriever_app, run_retriever_service
from src.agents.retrievers.clinical.tools import search_cdsco_drugs, search_clinical_trials

if TYPE_CHECKING:
    from src.shared.infra.audit import AuditService
    from src.shared.ports.session_store import SessionStore


class ClinicalRetriever(BaseRetriever):
    """Clinical pillar retriever - trial pipeline analysis."""

    def __init__(
        self,
        cosmos: SessionStore,
        audit: AuditService,
        subscription_name: str = "retriever-clinical-sub",
    ) -> None:
        super().__init__(cosmos=cosmos, audit=audit, subscription_name=subscription_name)

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
                drug_name=drug_name,
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
                drug_name=drug_name,
                status="RECRUITING",
            )
            findings["phase3_trials"] = [
                t for t in phase3 if "PHASE3" in str(t.get("phase", "")).upper()
            ]
            citations.append(p3_citation)
        except Exception as e:
            findings["phase3_error"] = str(e)

        # 3. CDSCO search if India market
        if target_market.lower() in ("india", "in"):
            try:
                cdsco_data, cdsco_citation = search_cdsco_drugs(drug_name, target_market)
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


app = create_retriever_app(
    ClinicalRetriever,
    agent_name="retriever-clinical",
    default_subscription="retriever-clinical-sub",
)


if __name__ == "__main__":
    run_retriever_service(app)

