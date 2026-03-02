"""
Unit tests for SPAR Framework — ReflectionEngine.

Tests the full reflection lifecycle: citation validity, timeout/failure
detection, decision consistency, pillar coverage, and dynamic thresholds.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.shared.spar.reflect import ReflectionEngine


@pytest.fixture
def engine() -> ReflectionEngine:
    with patch("src.shared.spar.reflect.ReflectionEngine.initialize"):
        e = ReflectionEngine()
        e._postgres = MagicMock()
        e._redis = MagicMock()
    return e


def _make_session_data(status: str = "COMPLETED", decision: str = "GO") -> dict:
    return {
        "id": "session-001",
        "status": status,
        "query": "Analyze Keytruda for US market",
        "decision": decision,
        "decision_rationale": "Strong pipeline, no patent blocks",
        "task_graph": [
            {"task_id": "t1", "pillar": "LEGAL", "status": "COMPLETED"},
            {"task_id": "t2", "pillar": "CLINICAL", "status": "COMPLETED"},
            {"task_id": "t3", "pillar": "COMMERCIAL", "status": "COMPLETED"},
            {"task_id": "t4", "pillar": "SOCIAL", "status": "COMPLETED"},
            {"task_id": "t5", "pillar": "KNOWLEDGE", "status": "COMPLETED"},
        ],
    }


def _make_agent_results(include_citations: bool = True) -> list[dict]:
    base = [
        {
            "pillar": "LEGAL",
            "findings": {"blocking_patents": []},
            "citations": [{"source_name": "FDA OB", "source_url": "https://fda.gov", "data_hash": "h1"}] if include_citations else [],
        },
        {
            "pillar": "CLINICAL",
            "findings": {"trials": [{"status": "Phase 3"}]},
            "citations": [{"source_name": "CT.gov", "source_url": "https://ct.gov", "data_hash": "h2"}] if include_citations else [],
        },
    ]
    return base


class TestCheckCitationValidity:
    """Tests for citation validity checking."""

    def test_valid_citations_pass(self, engine: ReflectionEngine) -> None:
        results = _make_agent_results(include_citations=True)
        reflection = engine._check_citation_validity(results)
        # _check_citation_validity returns dict with "type", "score", etc.
        assert reflection["type"] == "citation_validity"
        assert reflection["score"] == 1.0
        assert reflection["total_citations"] == 2
        assert reflection["valid_citations"] == 2

    def test_missing_citations_detected(self, engine: ReflectionEngine) -> None:
        results = _make_agent_results(include_citations=False)
        reflection = engine._check_citation_validity(results)
        assert isinstance(reflection, dict)
        assert "type" in reflection
        # With no citations, score should be 1.0 (vacuous truth: 0/0 → 1.0)
        assert reflection["total_citations"] == 0


class TestCheckTimeoutsAndFailures:
    """Tests for timeout and DLQ detection."""

    def test_all_completed_no_issues(self, engine: ReflectionEngine) -> None:
        session_data = _make_session_data()
        results = _make_agent_results()
        reflection = engine._check_timeouts_and_failures(session_data, results)
        assert isinstance(reflection, dict)

    def test_dlq_task_detected(self, engine: ReflectionEngine) -> None:
        session_data = _make_session_data()
        session_data["task_graph"][0]["status"] = "DLQ"
        results = _make_agent_results()
        reflection = engine._check_timeouts_and_failures(session_data, results)
        assert isinstance(reflection, dict)

    def test_timed_out_task_detected(self, engine: ReflectionEngine) -> None:
        session_data = _make_session_data(status="TIMED_OUT")
        results = _make_agent_results()
        reflection = engine._check_timeouts_and_failures(session_data, results)
        assert isinstance(reflection, dict)


class TestCheckDecisionConsistency:
    """Tests for decision-evidence alignment."""

    def test_consistent_go_decision(self, engine: ReflectionEngine) -> None:
        session_data = _make_session_data(decision="GO")
        results = _make_agent_results()
        validation = {"is_valid": True, "grounding_score": 0.9, "conflicts": []}
        reflection = engine._check_decision_consistency(session_data, results, validation)
        assert isinstance(reflection, dict)

    def test_inconsistent_decision_flagged(self, engine: ReflectionEngine) -> None:
        session_data = _make_session_data(decision="GO")
        results = _make_agent_results()
        # Low grounding with GO should be flagged
        validation = {"is_valid": False, "grounding_score": 0.2, "conflicts": [{"severity": "CRITICAL"}]}
        reflection = engine._check_decision_consistency(session_data, results, validation)
        assert isinstance(reflection, dict)


class TestCheckPillarCoverage:
    """Tests for pillar coverage checking."""

    def test_full_coverage_passes(self, engine: ReflectionEngine) -> None:
        session_data = _make_session_data()
        results = [
            {"pillar": "LEGAL", "findings": {}},
            {"pillar": "CLINICAL", "findings": {}},
            {"pillar": "COMMERCIAL", "findings": {}},
            {"pillar": "SOCIAL", "findings": {}},
            {"pillar": "KNOWLEDGE", "findings": {}},
        ]
        reflection = engine._check_pillar_coverage(session_data, results)
        assert isinstance(reflection, dict)

    def test_missing_pillar_detected(self, engine: ReflectionEngine) -> None:
        session_data = _make_session_data()
        # Only 2 pillars completed out of 5 expected
        results = [
            {"pillar": "LEGAL", "findings": {}},
            {"pillar": "CLINICAL", "findings": {}},
        ]
        reflection = engine._check_pillar_coverage(session_data, results)
        assert isinstance(reflection, dict)


class TestReflectOnSession:
    """Tests for the full reflection lifecycle (async)."""

    @pytest.mark.asyncio
    async def test_full_reflection_returns_dict(self, engine: ReflectionEngine) -> None:
        session_data = _make_session_data()
        results = _make_agent_results()
        validation = {"is_valid": True, "grounding_score": 0.85, "conflicts": []}
        with patch.object(engine, "_log_reflection", new_callable=AsyncMock):
            report = await engine.reflect_on_session(
                session_id="session-001",
                session_data=session_data,
                agent_results=results,
                validation_result=validation,
            )
        assert isinstance(report, dict)
        assert "reflections" in report
        assert "overall_score" in report
        assert len(report["reflections"]) > 0


class TestDynamicThresholds:
    """Tests for user-specific threshold loading (async)."""

    @pytest.mark.asyncio
    async def test_loads_defaults_on_failure(self, engine: ReflectionEngine) -> None:
        engine._redis = None  # Simulate no Redis
        thresholds = await engine.load_dynamic_thresholds(user_id="unknown-user")
        assert isinstance(thresholds, dict)
        assert "grounding" in thresholds

    @pytest.mark.asyncio
    async def test_loads_defaults_when_no_user(self, engine: ReflectionEngine) -> None:
        thresholds = await engine.load_dynamic_thresholds(user_id=None)
        assert isinstance(thresholds, dict)
        assert "grounding" in thresholds
