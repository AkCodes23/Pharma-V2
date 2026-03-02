"""
Unit tests for Executor Agent — ReportGenerator.

Tests context-constrained decoding, deterministic GO/NO-GO
decision logic, and edge cases (missing pillars, empty findings).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.executor.report_generator import ReportGenerator
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


def _make_agent_result(pillar: PillarType, findings: dict) -> AgentResult:
    """Helper to create a valid AgentResult with all required fields."""
    return AgentResult(
        task_id="task-001",
        session_id="test-session-001",
        agent_type=AgentType.LEGAL_RETRIEVER,
        pillar=pillar,
        findings=findings,
        citations=[
            Citation(
                source_name="FDA OB",
                source_url="https://fda.gov",
                excerpt="Test data",
                data_hash="abc123hash",
            )
        ],
        confidence=0.9,
        execution_time_ms=1500,
    )


def _make_session(
    agent_results: list[AgentResult] | None = None,
    validation: ValidationResult | None = None,
) -> Session:
    """Helper to create a mock session with plausible data."""
    default_results = agent_results if agent_results is not None else [
        _make_agent_result(PillarType.LEGAL, {"blocking_patents": [], "patent_status": "CLEAR"}),
        _make_agent_result(PillarType.CLINICAL, {"trials": [{"status": "Phase 3"}], "pipeline_strength": "STRONG"}),
        _make_agent_result(PillarType.COMMERCIAL, {"revenue_data": {"total": 5_000_000_000}, "market_attractiveness": "HIGH"}),
    ]
    default_validation = validation if validation is not None else ValidationResult(
        is_valid=True,
        grounding_score=0.85,
        conflicts=[],
        validation_notes="All results well-grounded.",
    )
    return Session(
        id="test-session-001",
        user_id="test-user",
        query="Analyze Keytruda market entry strategy for US by 2027",
        parameters=QueryParameters(
            drug_name="Pembrolizumab",
            brand_name="Keytruda",
            target_market="US",
            time_horizon="2027",
            therapeutic_area="Oncology",
        ),
        status=SessionStatus.SYNTHESIZING,
        task_graph=[
            TaskNode(session_id="test-session-001", pillar=PillarType.LEGAL, description="Legal check", parameters={}),
        ],
        agent_results=default_results,
        validation=default_validation,
    )


@pytest.fixture
def report_gen() -> ReportGenerator:
    with patch("src.agents.executor.report_generator.get_settings") as mock_settings:
        settings = MagicMock()
        settings.openai.endpoint = "https://test.openai.azure.com"
        settings.openai.api_key = "test-key"
        settings.openai.deployment_name = "gpt-4o"
        settings.openai.api_version = "2024-12-01-preview"
        mock_settings.return_value = settings
        gen = ReportGenerator()
    return gen


class TestGenerateReport:
    """Tests for report generation."""

    def test_returns_markdown_and_decision(self, report_gen: ReportGenerator) -> None:
        session = _make_session()
        llm_content = "# Strategic Assessment\n\n## Legal Analysis\nNo blocking patents found..."
        with patch.object(report_gen, "_http_client") as mock_http:
            resp = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": llm_content}}]}
            resp.raise_for_status = MagicMock()
            mock_http.post.return_value = resp
            markdown, decision, rationale = report_gen.generate_report(session)

        assert isinstance(markdown, str)
        assert len(markdown) > 0
        assert decision in (DecisionOutcome.GO, DecisionOutcome.NO_GO, DecisionOutcome.CONDITIONAL_GO)
        assert isinstance(rationale, str)


class TestDetermineDecision:
    """Tests for deterministic GO/NO-GO decision logic."""

    def test_go_decision_clean_session(self, report_gen: ReportGenerator) -> None:
        """GO when high market attractiveness, no blocking patents, no conflicts."""
        session = _make_session()
        session.validation = ValidationResult(
            is_valid=True, grounding_score=0.9, conflicts=[], validation_notes="Clean.",
        )
        decision, rationale = report_gen._determine_decision(session)
        assert decision == DecisionOutcome.GO

    def test_no_go_on_critical_conflict(self, report_gen: ReportGenerator) -> None:
        """NO_GO when CRITICAL conflict exists."""
        session = _make_session(
            validation=ValidationResult(
                is_valid=False,
                grounding_score=0.4,
                conflicts=[
                    ConflictDetail(
                        conflict_type="SAFETY_ALERT",
                        pillars_involved=[PillarType.SOCIAL, PillarType.CLINICAL],
                        description="Critical safety signal",
                        severity=ConflictSeverity.CRITICAL,
                        recommendation="Do not proceed",
                    ),
                ],
                validation_notes="Critical safety issue.",
            ),
        )
        decision, rationale = report_gen._determine_decision(session)
        assert decision == DecisionOutcome.NO_GO
        assert "Critical" in rationale

    def test_conditional_on_blocking_patents(self, report_gen: ReportGenerator) -> None:
        """CONDITIONAL_GO when blocking patents exist."""
        session = _make_session(
            agent_results=[
                _make_agent_result(PillarType.LEGAL, {
                    "blocking_patents": [{"patent_number": "US12345", "expiry_date": "2028-06-15"}],
                    "earliest_generic_entry": "2028-06-15",
                }),
                _make_agent_result(PillarType.COMMERCIAL, {"market_attractiveness": "HIGH"}),
            ],
            validation=ValidationResult(
                is_valid=True,
                grounding_score=0.85,
                conflicts=[],
                validation_notes="Valid.",
            ),
        )
        decision, rationale = report_gen._determine_decision(session)
        assert decision == DecisionOutcome.CONDITIONAL_GO
        assert "patent" in rationale.lower()

    def test_conditional_on_high_severity_conflicts(self, report_gen: ReportGenerator) -> None:
        """CONDITIONAL_GO when HIGH severity conflict exists (no CRITICAL)."""
        session = _make_session(
            validation=ValidationResult(
                is_valid=True,
                grounding_score=0.75,
                conflicts=[
                    ConflictDetail(
                        conflict_type="DATA_GAP",
                        pillars_involved=[PillarType.KNOWLEDGE, PillarType.CLINICAL],
                        description="Limited trial data",
                        severity=ConflictSeverity.HIGH,
                        recommendation="Gather more data",
                    ),
                ],
                validation_notes="Partial data.",
            ),
        )
        decision, _ = report_gen._determine_decision(session)
        assert decision == DecisionOutcome.CONDITIONAL_GO

    def test_insufficient_data_on_low_grounding(self, report_gen: ReportGenerator) -> None:
        """INSUFFICIENT_DATA when grounding score < 0.5 and no other triggers."""
        session = _make_session(
            agent_results=[
                _make_agent_result(PillarType.LEGAL, {"blocking_patents": []}),
                _make_agent_result(PillarType.COMMERCIAL, {"market_attractiveness": "LOW"}),
            ],
            validation=ValidationResult(
                is_valid=True,
                grounding_score=0.3,
                conflicts=[],
                validation_notes="Very low grounding.",
            ),
        )
        decision, rationale = report_gen._determine_decision(session)
        assert decision == DecisionOutcome.INSUFFICIENT_DATA
        assert "grounding" in rationale.lower() or "Grounding" in rationale


class TestReportEdgeCases:
    """Tests for edge cases in report generation."""

    def test_empty_agent_results(self, report_gen: ReportGenerator) -> None:
        session = _make_session(agent_results=[])
        llm_content = "# Report\n\nINSUFFICIENT DATA for all sections."
        with patch.object(report_gen, "_http_client") as mock_http:
            resp = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": llm_content}}]}
            resp.raise_for_status = MagicMock()
            mock_http.post.return_value = resp
            markdown, decision, rationale = report_gen.generate_report(session)

        assert isinstance(markdown, str)

    def test_missing_validation_returns_insufficient_data(self, report_gen: ReportGenerator) -> None:
        """When validation is None, decision should be INSUFFICIENT_DATA."""
        session = _make_session()
        session.validation = None
        decision, rationale = report_gen._determine_decision(session)
        assert decision == DecisionOutcome.INSUFFICIENT_DATA
        assert "Validation" in rationale
