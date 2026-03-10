"""
Pharma Agentic AI — Unit Tests: Shared Models.

Tests for Pydantic model validation, enum consistency,
and schema enforcement across the platform.
"""

import pytest
from pydantic import ValidationError

from src.shared.models.enums import (
    AgentType,
    AuditAction,
    ConflictSeverity,
    DecisionOutcome,
    PillarType,
    SessionStatus,
    TaskStatus,
)
from src.shared.models.schemas import (
    AgentResult,
    AuditEntry,
    Citation,
    ConflictDetail,
    QueryParameters,
    Session,
    TaskNode,
    ValidationResult,
)

# ── Citation Tests ──────────────────────────────────────────


class TestCitation:
    """Tests for Citation model and SHA-256 hashing."""

    def test_create_citation(self):
        """A valid citation should be created with all fields."""
        citation = Citation(
            source_name="FDA Orange Book",
            source_url="https://api.fda.gov/drug/drugsfda.json",
            data_hash=Citation.compute_hash("test payload"),
            excerpt="Found 5 records",
        )
        assert citation.source_name == "FDA Orange Book"
        assert len(citation.data_hash) == 64  # SHA-256 hex length
        assert citation.retrieved_at is not None

    def test_compute_hash_consistency(self):
        """The same payload should always produce the same hash."""
        payload = '{"test": "data", "number": 42}'
        hash1 = Citation.compute_hash(payload)
        hash2 = Citation.compute_hash(payload)
        assert hash1 == hash2

    def test_compute_hash_different_payloads(self):
        """Different payloads should produce different hashes."""
        hash1 = Citation.compute_hash("payload_a")
        hash2 = Citation.compute_hash("payload_b")
        assert hash1 != hash2

    def test_compute_hash_bytes(self):
        """Hash should work with both str and bytes input."""
        str_hash = Citation.compute_hash("test")
        bytes_hash = Citation.compute_hash(b"test")
        assert str_hash == bytes_hash


# ── QueryParameters Tests ───────────────────────────────────


class TestQueryParameters:
    """Tests for QueryParameters model."""

    def test_required_fields(self):
        """Required fields must be provided."""
        params = QueryParameters(
            drug_name="Pembrolizumab",
            target_market="India",
            time_horizon="2027",
        )
        assert params.drug_name == "Pembrolizumab"
        assert params.brand_name is None  # Optional

    def test_optional_fields(self):
        """Optional fields should accept None."""
        params = QueryParameters(
            drug_name="Pembrolizumab",
            brand_name="Keytruda",
            target_market="India",
            time_horizon="2027",
            therapeutic_area="Oncology",
        )
        assert params.brand_name == "Keytruda"
        assert params.therapeutic_area == "Oncology"


# ── TaskNode Tests ──────────────────────────────────────────


class TestTaskNode:
    """Tests for TaskNode model."""

    def test_default_status(self):
        """New tasks should default to QUEUED."""
        task = TaskNode(
            session_id="sess-001",
            pillar=PillarType.LEGAL,
            description="Search USPTO for patent data",
        )
        assert task.status == TaskStatus.QUEUED
        assert task.retry_count == 0

    def test_auto_generated_id(self):
        """Task ID should be auto-generated."""
        task = TaskNode(
            session_id="sess-001",
            pillar=PillarType.CLINICAL,
            description="Search ClinicalTrials.gov",
        )
        assert task.task_id is not None
        assert len(task.task_id) > 0


# ── AgentResult Tests ───────────────────────────────────────


class TestAgentResult:
    """Tests for AgentResult model."""

    def test_create_result(self):
        """Agent results should include findings and citations."""
        result = AgentResult(
            task_id="task-001",
            session_id="sess-001",
            agent_type=AgentType.LEGAL_RETRIEVER,
            pillar=PillarType.LEGAL,
            findings={"patents": [{"number": "US123456"}]},
            citations=[
                Citation(
                    source_name="USPTO",
                    source_url="https://api.fda.gov/...",
                    data_hash=Citation.compute_hash("test"),
                    excerpt="1 patent found",
                )
            ],
            confidence=0.95,
            execution_time_ms=2340,
        )
        assert result.confidence == 0.95
        assert len(result.citations) == 1

    def test_confidence_bounds(self):
        """Confidence must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            AgentResult(
                task_id="task-001",
                session_id="sess-001",
                agent_type=AgentType.LEGAL_RETRIEVER,
                pillar=PillarType.LEGAL,
                findings={},
                citations=[
                    Citation(
                        source_name="test",
                        source_url="url",
                        data_hash="hash",
                        excerpt="excerpt",
                    )
                ],
                confidence=1.5,  # Invalid
                execution_time_ms=100,
            )


# ── ValidationResult Tests ──────────────────────────────────


class TestValidationResult:
    """Tests for ValidationResult model."""

    def test_valid_result(self):
        """A valid result should have is_valid=True."""
        result = ValidationResult(
            is_valid=True,
            grounding_score=0.95,
            validation_notes="All checks passed",
        )
        assert result.is_valid is True
        assert result.conflicts == []

    def test_with_conflicts(self):
        """Conflicts should be properly stored."""
        result = ValidationResult(
            is_valid=False,
            grounding_score=0.6,
            conflicts=[
                ConflictDetail(
                    conflict_type="PATENT_MARKET_CONFLICT",
                    pillars_involved=[PillarType.LEGAL, PillarType.COMMERCIAL],
                    description="Patent blocks market entry",
                    severity=ConflictSeverity.CRITICAL,
                    recommendation="Delay launch",
                )
            ],
        )
        assert len(result.conflicts) == 1
        assert result.conflicts[0].severity == ConflictSeverity.CRITICAL


# ── Session Tests ───────────────────────────────────────────


class TestSession:
    """Tests for Session model."""

    def test_create_session(self):
        """Session should be created with default values."""
        session = Session(
            user_id="user-001",
            query="Assess Keytruda in India",
            parameters=QueryParameters(
                drug_name="Pembrolizumab",
                target_market="India",
                time_horizon="2027",
            ),
        )
        assert session.status == SessionStatus.PENDING
        assert session.decision is None
        assert session.report_url is None

    def test_session_id_generated(self):
        """Session ID should be auto-generated."""
        session = Session(
            user_id="user-001",
            query="Test query",
            parameters=QueryParameters(
                drug_name="Test",
                target_market="US",
                time_horizon="2026",
            ),
        )
        assert session.id is not None


# ── AuditEntry Tests ────────────────────────────────────────


class TestAuditEntry:
    """Tests for AuditEntry model."""

    def test_create_audit_entry(self):
        """Audit entries should enforce all required fields."""
        entry = AuditEntry(
            session_id="sess-001",
            user_id="user-001",
            agent_id="planner-abc123",
            agent_type=AgentType.PLANNER,
            action=AuditAction.QUERY_SUBMITTED,
            payload_hash=Citation.compute_hash('{"query": "test"}'),
            details={"query": "test"},
        )
        assert entry.action == AuditAction.QUERY_SUBMITTED
        assert len(entry.payload_hash) == 64


# ── Enum Tests ──────────────────────────────────────────────


class TestEnums:
    """Tests for enum completeness and serialization."""

    def test_pillar_types(self):
        """All 6 pillar types should exist."""
        assert len(PillarType) == 6
        assert PillarType.LEGAL.value == "LEGAL"
        assert PillarType.NEWS.value == "NEWS"

    def test_agent_types(self):
        """All 11 agent types should exist."""
        assert len(AgentType) == 11
        assert AgentType.NEWS_RETRIEVER.value == "NEWS_RETRIEVER"
        assert AgentType.QUALITY_EVALUATOR.value == "QUALITY_EVALUATOR"
        assert AgentType.PROMPT_ENHANCER.value == "PROMPT_ENHANCER"

    def test_session_status_lifecycle(self):
        """Session statuses should cover the full lifecycle."""
        statuses = [s.value for s in SessionStatus]
        assert "PENDING" in statuses
        assert "COMPLETED" in statuses
        assert "FAILED" in statuses

    def test_decision_outcomes(self):
        """Decision outcomes should cover all possibilities."""
        assert DecisionOutcome.GO.value == "GO"
        assert DecisionOutcome.NO_GO.value == "NO_GO"
        assert DecisionOutcome.CONDITIONAL_GO.value == "CONDITIONAL_GO"

    def test_enum_string_serialization(self):
        """StrEnum values should serialize to strings."""
        assert str(PillarType.LEGAL) == "LEGAL"
        assert str(AgentType.PLANNER) == "PLANNER"
