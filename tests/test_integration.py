"""
Pharma Agentic AI — Integration Tests: Agent Pipeline.

Tests the full flow: Planner → Service Bus → Retriever → Cosmos DB.
Uses mocked Azure services for local testing without cloud resources.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

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

# ── Imports for agents under test ───────────────────────────

from src.agents.retrievers.legal.tools import search_ipo_patents
from src.agents.retrievers.clinical.tools import search_cdsco
from src.agents.retrievers.commercial.tools import get_market_data, get_drug_revenue
from src.agents.retrievers.social.tools import compute_safety_score
from src.agents.retrievers.knowledge.tools import hybrid_search
from src.agents.supervisor.conflict_resolver import ConflictResolver, ResolutionAction
from src.agents.executor.report_generator import ReportGenerator


# ── Mock Tool Tests ─────────────────────────────────────────


class TestMockTools:
    """Tests for mock API tools (used in MVP before real integrations)."""

    def test_ipo_search_returns_mock_data(self):
        """IPO search should return structured mock patent data."""
        patents, citation = search_ipo_patents("Pembrolizumab", "India")
        assert len(patents) > 0
        assert patents[0]["ingredient"] == "Pembrolizumab"
        assert patents[0]["market"] == "India"
        assert citation.source_name == "Indian Patent Office (IPO)"
        assert "[MOCK]" in citation.excerpt

    def test_cdsco_search_returns_mock_data(self):
        """CDSCO search should return India-specific approval data."""
        results, citation = search_cdsco("Pembrolizumab", "India")
        assert len(results) > 0
        assert results[0]["drug_name"] == "Pembrolizumab"
        assert citation.source_name == "CDSCO Drug Database"

    def test_market_data_returns_structured_data(self):
        """Market data tool should return TAM, CAGR, competitors."""
        data, citation = get_market_data("Pembrolizumab", "Oncology", "India")
        assert data["total_addressable_market_usd"] > 0
        assert data["market_growth_cagr_pct"] > 0
        assert len(data["key_competitors"]) > 0
        assert "[MOCK]" in citation.excerpt

    def test_drug_revenue_returns_historicals(self):
        """Revenue tool should return historical revenue by year."""
        data, citation = get_drug_revenue("Keytruda")
        assert len(data["annual_revenue"]) > 0
        assert data["peak_sales_usd"] > 0
        assert data["peak_year"] > 2020

    def test_safety_score_computation(self):
        """Safety score should be deterministic based on events."""
        events = [
            {"serious": 1, "seriousness_death": 0, "seriousness_hospitalization": 1, "reactions": ["HEADACHE"]},
            {"serious": 0, "seriousness_death": 0, "seriousness_hospitalization": 0, "reactions": ["NAUSEA"]},
            {"serious": 0, "seriousness_death": 0, "seriousness_hospitalization": 0, "reactions": ["FATIGUE"]},
            {"serious": 1, "seriousness_death": 1, "seriousness_hospitalization": 0, "reactions": ["CARDIAC ARREST"]},
        ]
        score = compute_safety_score(events)
        assert score["total_events"] == 4
        assert score["serious_count"] == 2
        assert score["death_count"] == 1
        assert score["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    def test_safety_score_empty_events(self):
        """Safety score should handle empty event lists."""
        score = compute_safety_score([])
        assert score["risk_level"] == "LOW"
        assert score["total_events"] == 0

    def test_hybrid_search_returns_documents(self):
        """Hybrid search should return internal document results."""
        results, citation = hybrid_search("oncology portfolio strategy")
        assert len(results) > 0
        assert results[0]["document_id"] is not None
        assert citation.source_name == "Azure AI Search (Internal Documents)"


# ── Conflict Resolver Tests ─────────────────────────────────


class TestConflictResolver:
    """Tests for severity-based conflict resolution."""

    def test_low_severity_auto_resolved(self):
        """LOW conflicts should be auto-resolved."""
        resolver = ConflictResolver()
        conflicts = [
            ConflictDetail(
                conflict_type="MINOR_DATA_GAP",
                pillars_involved=[PillarType.KNOWLEDGE],
                description="Minor gap in internal data",
                severity=ConflictSeverity.LOW,
                recommendation="No action needed",
            )
        ]
        resolutions = resolver.resolve(conflicts)
        assert len(resolutions) == 1
        assert resolutions[0].action == ResolutionAction.AUTO_RESOLVED
        resolver.close()

    def test_medium_severity_annotated(self):
        """MEDIUM conflicts should be annotated as Strategic Risks."""
        resolver = ConflictResolver()
        conflicts = [
            ConflictDetail(
                conflict_type="DATA_GAP",
                pillars_involved=[PillarType.COMMERCIAL, PillarType.CLINICAL],
                description="Mixed signals from market vs trial data",
                severity=ConflictSeverity.MEDIUM,
                recommendation="Investigate further",
            )
        ]
        resolutions = resolver.resolve(conflicts)
        assert resolutions[0].action == ResolutionAction.ANNOTATED
        assert "STRATEGIC RISK" in resolutions[0].annotation
        resolver.close()

    def test_critical_severity_escalated(self):
        """CRITICAL conflicts should be escalated (even without webhook)."""
        resolver = ConflictResolver()
        conflicts = [
            ConflictDetail(
                conflict_type="PATENT_MARKET_CONFLICT",
                pillars_involved=[PillarType.LEGAL, PillarType.COMMERCIAL],
                description="Active blocking patent prevents market entry",
                severity=ConflictSeverity.CRITICAL,
                recommendation="Delay launch until 2028",
            )
        ]
        resolutions = resolver.resolve(conflicts)
        assert resolutions[0].action == ResolutionAction.ESCALATED
        assert "HUMAN REVIEW REQUIRED" in resolutions[0].annotation
        resolver.close()


# ── Decision Engine Tests ───────────────────────────────────


class TestDecisionEngine:
    """Tests for the deterministic GO/NO-GO decision engine."""

    def _make_session(
        self,
        blocking_patents: list | None = None,
        market_attractiveness: str = "HIGH",
        grounding_score: float = 0.95,
        conflicts: list[ConflictDetail] | None = None,
    ) -> Session:
        """Helper to create a test session with configurable params."""
        legal_result = AgentResult(
            task_id="t1",
            session_id="s1",
            agent_type=AgentType.LEGAL_RETRIEVER,
            pillar=PillarType.LEGAL,
            findings={
                "blocking_patents": blocking_patents or [],
                "earliest_generic_entry": "2028-03-15" if blocking_patents else None,
            },
            citations=[Citation(source_name="test", source_url="url", data_hash="abc", excerpt="test")],
            confidence=0.9,
            execution_time_ms=1000,
        )

        commercial_result = AgentResult(
            task_id="t2",
            session_id="s1",
            agent_type=AgentType.COMMERCIAL_RETRIEVER,
            pillar=PillarType.COMMERCIAL,
            findings={"market_attractiveness": market_attractiveness},
            citations=[Citation(source_name="test", source_url="url", data_hash="def", excerpt="test")],
            confidence=0.9,
            execution_time_ms=800,
        )

        validation = ValidationResult(
            is_valid=grounding_score >= 0.8,
            grounding_score=grounding_score,
            conflicts=conflicts or [],
        )

        return Session(
            user_id="test-user",
            query="Test query",
            parameters=QueryParameters(drug_name="Test", target_market="US", time_horizon="2027"),
            agent_results=[legal_result, commercial_result],
            validation=validation,
        )

    def test_go_decision_no_blockers(self):
        """No blocking patents + high market → GO."""
        gen = ReportGenerator.__new__(ReportGenerator)
        session = self._make_session(market_attractiveness="HIGH")
        decision, rationale = gen._determine_decision(session)
        assert decision == DecisionOutcome.GO

    def test_conditional_go_with_patents(self):
        """Blocking patents exist → CONDITIONAL_GO."""
        gen = ReportGenerator.__new__(ReportGenerator)
        session = self._make_session(
            blocking_patents=[{"patent_number": "US123", "expiry_date": "2028-03-15"}]
        )
        decision, rationale = gen._determine_decision(session)
        assert decision == DecisionOutcome.CONDITIONAL_GO
        assert "patent" in rationale.lower()

    def test_no_go_critical_conflict(self):
        """Critical conflict → NO_GO."""
        gen = ReportGenerator.__new__(ReportGenerator)
        conflict = ConflictDetail(
            conflict_type="PATENT_MARKET_CONFLICT",
            pillars_involved=[PillarType.LEGAL, PillarType.COMMERCIAL],
            description="Active patent blocks entry",
            severity=ConflictSeverity.CRITICAL,
            recommendation="Delay",
        )
        session = self._make_session(conflicts=[conflict])
        decision, rationale = gen._determine_decision(session)
        assert decision == DecisionOutcome.NO_GO

    def test_insufficient_data_low_grounding(self):
        """Low grounding score → INSUFFICIENT_DATA."""
        gen = ReportGenerator.__new__(ReportGenerator)
        session = self._make_session(grounding_score=0.3, market_attractiveness="LOW")
        decision, rationale = gen._determine_decision(session)
        assert decision == DecisionOutcome.INSUFFICIENT_DATA
