from __future__ import annotations

from src.shared.adapters.fixture_report_generator import FixtureReportGenerator
from src.shared.models.enums import (
    AgentType,
    ConflictSeverity,
    DecisionOutcome,
    PillarType,
    SessionStatus,
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


def _citation() -> Citation:
    return Citation(
        source_name="fixture",
        source_url="local://fixture",
        data_hash="abc123",
        excerpt="deterministic fixture",
    )


def _session(*, blockers: bool = False, critical_conflict: bool = False) -> Session:
    legal_task = TaskNode(session_id="s-1", pillar=PillarType.LEGAL, description="legal")

    legal_findings = {
        "blocking_patents": [{"patent_number": "IN-123"}] if blockers else [],
        "earliest_generic_entry": "2029-01-01" if blockers else None,
    }

    result = AgentResult(
        task_id=legal_task.task_id,
        session_id="s-1",
        agent_type=AgentType.LEGAL_RETRIEVER,
        pillar=PillarType.LEGAL,
        findings=legal_findings,
        citations=[_citation()],
        confidence=0.9,
        execution_time_ms=100,
    )

    conflicts = []
    if critical_conflict:
        conflicts.append(
            ConflictDetail(
                conflict_type="PATENT_MARKET_CONFLICT",
                pillars_involved=[PillarType.LEGAL, PillarType.COMMERCIAL],
                description="Critical legal blockage",
                severity=ConflictSeverity.CRITICAL,
                recommendation="Do not proceed",
            )
        )

    validation = ValidationResult(
        is_valid=not critical_conflict,
        conflicts=conflicts,
        grounding_score=0.95,
        validation_notes="ok",
    )

    return Session(
        id="s-1",
        user_id="demo-user",
        query="Assess Keytruda launch",
        parameters=QueryParameters(
            drug_name="Pembrolizumab",
            brand_name="Keytruda",
            target_market="India",
            time_horizon="2027",
            therapeutic_area="Oncology",
        ),
        status=SessionStatus.SYNTHESIZING,
        task_graph=[legal_task],
        agent_results=[result],
        validation=validation,
    )


def test_fixture_report_generator_returns_conditional_go_for_blockers() -> None:
    generator = FixtureReportGenerator()
    session = _session(blockers=True)

    markdown, decision, rationale = generator.generate_report(session)

    assert decision == DecisionOutcome.CONDITIONAL_GO
    assert "Blocking patents" in rationale
    assert "Assess Keytruda launch" in markdown


def test_fixture_report_generator_returns_no_go_for_critical_conflict() -> None:
    generator = FixtureReportGenerator()
    session = _session(blockers=False, critical_conflict=True)

    _, decision, rationale = generator.generate_report(session)

    assert decision == DecisionOutcome.NO_GO
    assert "Critical conflict" in rationale
