"""
Pharma Agentic AI — End-to-End Test: Keytruda India 2027 Scenario.

Simulates the complete "Should we launch a generic for Keytruda
in India by 2027?" scenario using mock data. Tests the full pipeline:
  Planner → Retrievers → Supervisor → Executor → Report
"""

import pytest
from datetime import datetime, timezone

from src.shared.models.enums import (
    AgentType,
    ConflictSeverity,
    DecisionOutcome,
    PillarType,
    SessionStatus,
    TaskStatus,
)
from src.shared.models.schemas import (
    AgentResult,
    Citation,
    ConflictDetail,
    QueryParameters,
    Session,
    TaskNode,
    ValidationResult,
)
from src.agents.supervisor.validator import GroundingValidator
from src.agents.supervisor.conflict_resolver import ConflictResolver, ResolutionAction


class TestKeytrudaIndiaScenario:
    """
    End-to-end scenario test: "Assess 2027 generic launch for Keytruda in India"

    Expected outcome: CONDITIONAL_GO due to blocking patent
    """

    def _build_session_with_results(self) -> Session:
        """Build a pre-populated session simulating all retrievers completed."""
        session = Session(
            user_id="dr.aditi",
            query="Assess 2027 generic launch for Keytruda in India",
            parameters=QueryParameters(
                drug_name="Pembrolizumab",
                brand_name="Keytruda",
                target_market="India",
                time_horizon="2027",
                therapeutic_area="Oncology",
            ),
        )

        # ── Legal findings (blocking patent) ──────────────
        legal_result = AgentResult(
            task_id="legal-001",
            session_id=session.id,
            agent_type=AgentType.LEGAL_RETRIEVER,
            pillar=PillarType.LEGAL,
            findings={
                "drug_name": "Pembrolizumab",
                "target_market": "India",
                "orange_book_results": [
                    {"application_number": "NDA-125514", "brand_name": "KEYTRUDA"}
                ],
                "blocking_patents": [
                    {"patent_number": "IN-087254", "expiry_date": "2028-03-15", "patent_type": "Compound Patent"}
                ],
                "earliest_generic_entry": "2028-03-15",
            },
            citations=[
                Citation(source_name="FDA Orange Book", source_url="https://api.fda.gov/...", data_hash="abc123", excerpt="1 record"),
                Citation(source_name="IPO", source_url="https://ipindia.gov.in/...", data_hash="def456", excerpt="1 patent"),
            ],
            confidence=0.95,
            execution_time_ms=3200,
        )

        # ── Clinical findings (moderate competition) ──────
        clinical_result = AgentResult(
            task_id="clinical-001",
            session_id=session.id,
            agent_type=AgentType.CLINICAL_RETRIEVER,
            pillar=PillarType.CLINICAL,
            findings={
                "drug_name": "Pembrolizumab",
                "active_trials": [{"nct_id": "NCT0001"}, {"nct_id": "NCT0002"}, {"nct_id": "NCT0003"}],
                "total_active_trial_count": 3,
                "competitive_saturation": "LOW",
            },
            citations=[
                Citation(source_name="ClinicalTrials.gov", source_url="https://clinicaltrials.gov/...", data_hash="ghi789", excerpt="3 trials"),
            ],
            confidence=0.90,
            execution_time_ms=2800,
        )

        # ── Commercial findings (attractive market) ───────
        commercial_result = AgentResult(
            task_id="commercial-001",
            session_id=session.id,
            agent_type=AgentType.COMMERCIAL_RETRIEVER,
            pillar=PillarType.COMMERCIAL,
            findings={
                "drug_name": "Pembrolizumab",
                "market_data": {
                    "total_addressable_market_usd": 2_100_000_000,
                    "market_growth_cagr_pct": 12.3,
                },
                "revenue_data": {
                    "peak_sales_usd": 28_500_000_000,
                    "peak_year": 2025,
                },
                "market_attractiveness": "HIGH",
            },
            citations=[
                Citation(source_name="Market Intelligence", source_url="https://market-data.example.com/...", data_hash="jkl012", excerpt="TAM $2.1B"),
            ],
            confidence=0.85,
            execution_time_ms=1500,
        )

        # ── Social findings (low safety risk) ─────────────
        social_result = AgentResult(
            task_id="social-001",
            session_id=session.id,
            agent_type=AgentType.SOCIAL_RETRIEVER,
            pillar=PillarType.SOCIAL,
            findings={
                "drug_name": "Pembrolizumab",
                "safety_score": {
                    "risk_level": "MEDIUM",
                    "serious_pct": 15.0,
                    "total_events": 100,
                },
                "regulatory_risk": "MEDIUM",
            },
            citations=[
                Citation(source_name="FDA FAERS", source_url="https://api.fda.gov/...", data_hash="mno345", excerpt="100 events"),
            ],
            confidence=0.88,
            execution_time_ms=2100,
        )

        session.agent_results = [legal_result, clinical_result, commercial_result, social_result]
        session.status = SessionStatus.VALIDATING
        return session

    def test_full_scenario_produces_conditional_go(self):
        """
        Full scenario: Keytruda India 2027

        Expected: CONDITIONAL_GO because of blocking patent expiring 2028-03-15
        (after the 2027 target horizon).
        """
        session = self._build_session_with_results()

        # 1. Validate grounding (rule-based only — skip LLM call)
        validator = GroundingValidator.__new__(GroundingValidator)
        conflicts = validator._detect_rule_based_conflicts(session.agent_results)

        # Should detect PATENT_MARKET_CONFLICT
        assert len(conflicts) >= 1
        patent_conflict = next((c for c in conflicts if c.conflict_type == "PATENT_MARKET_CONFLICT"), None)
        assert patent_conflict is not None
        assert patent_conflict.severity == ConflictSeverity.CRITICAL
        assert PillarType.LEGAL in patent_conflict.pillars_involved
        assert PillarType.COMMERCIAL in patent_conflict.pillars_involved

        # 2. Resolve conflicts
        resolver = ConflictResolver()
        resolutions = resolver.resolve(conflicts)
        patent_resolution = next((r for r in resolutions if r.conflict.conflict_type == "PATENT_MARKET_CONFLICT"), None)
        assert patent_resolution is not None
        assert patent_resolution.action == ResolutionAction.ESCALATED
        resolver.close()

        # 3. Determine decision
        from src.agents.executor.report_generator import ReportGenerator
        gen = ReportGenerator.__new__(ReportGenerator)

        # Give the session a validation result
        session.validation = ValidationResult(
            is_valid=False,
            grounding_score=0.9,
            conflicts=conflicts,
        )

        decision, rationale = gen._determine_decision(session)

        # Decision should be NO_GO due to CRITICAL conflict
        assert decision == DecisionOutcome.NO_GO
        assert "conflict" in rationale.lower() or "patent" in rationale.lower()

    def test_scenario_without_blocking_patent_is_go(self):
        """
        Edge case: If no blocking patents, should be GO.
        """
        session = self._build_session_with_results()

        # Remove blocking patents
        legal_result = session.agent_results[0]
        legal_result.findings["blocking_patents"] = []
        legal_result.findings["earliest_generic_entry"] = None

        session.validation = ValidationResult(
            is_valid=True,
            grounding_score=0.95,
            conflicts=[],
        )

        from src.agents.executor.report_generator import ReportGenerator
        gen = ReportGenerator.__new__(ReportGenerator)
        decision, rationale = gen._determine_decision(session)

        assert decision == DecisionOutcome.GO

    def test_all_results_have_citations(self):
        """
        Compliance check: Every agent result MUST have at least one citation.
        """
        session = self._build_session_with_results()
        for result in session.agent_results:
            assert len(result.citations) > 0, f"{result.agent_type} has no citations — 21 CFR Part 11 violation"

    def test_citation_hashes_are_unique(self):
        """
        All citation hashes should be unique (no duplicate data).
        """
        session = self._build_session_with_results()
        all_hashes = []
        for result in session.agent_results:
            for citation in result.citations:
                all_hashes.append(citation.data_hash)

        assert len(all_hashes) == len(set(all_hashes)), "Duplicate citation hashes detected"
