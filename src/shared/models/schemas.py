"""
Pharma Agentic AI — Pydantic Schema Definitions.

Core data models shared across all agents. These schemas enforce
strict type safety and serve as the contract between:
  - Planner → Service Bus → Retrievers
  - Retrievers → Cosmos DB → Supervisor
  - Supervisor → Executor → Blob Storage
  - All components → Audit Trail

Every field is explicitly typed. No implicit coercion. No optional
fields without documented rationale.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from src.shared.models.enums import (
    AgentType,
    AuditAction,
    ConflictSeverity,
    DecisionOutcome,
    PillarType,
    SessionStatus,
    TaskStatus,
)


def _generate_id() -> str:
    """Generate a UUID4 string identifier."""
    return str(uuid4())


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


# ============================================================
# Query & Task Models
# ============================================================


class QueryParameters(BaseModel):
    """Structured parameters extracted from a natural-language query."""

    drug_name: str = Field(..., description="Generic/INN drug name (e.g., Pembrolizumab)")
    brand_name: str | None = Field(None, description="Brand name (e.g., Keytruda)")
    target_market: str = Field(..., description="ISO country or region (e.g., India, US, EU)")
    time_horizon: str = Field(..., description="Target year for market entry (e.g., 2027)")
    therapeutic_area: str | None = Field(None, description="Therapeutic area (e.g., Oncology)")
    additional_context: str | None = Field(None, description="Any extra context from the user")


class TaskNode(BaseModel):
    """
    A single unit of work in the task DAG.

    Each TaskNode maps to exactly one retriever agent and one pillar.
    The Planner generates these; the Service Bus routes them.
    """

    task_id: str = Field(default_factory=_generate_id)
    session_id: str = Field(..., description="Parent session ID")
    pillar: PillarType = Field(..., description="Which strategic pillar this task addresses")
    description: str = Field(..., description="Human-readable description of what to retrieve")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Pillar-specific query params")
    status: TaskStatus = Field(default=TaskStatus.QUEUED)
    retry_count: int = Field(default=0, ge=0, le=3)
    created_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = Field(default=None)
    error_message: str | None = Field(default=None)


# ============================================================
# Agent Result & Citation Models
# ============================================================


class Citation(BaseModel):
    """
    Immutable citation tracing a claim back to its source API.

    Every data point in the system MUST have at least one Citation.
    The Supervisor validates citation existence and integrity.
    """

    source_name: str = Field(..., description="E.g., 'USPTO Orange Book', 'ClinicalTrials.gov'")
    source_url: str = Field(..., description="Exact API endpoint or URL accessed")
    retrieved_at: datetime = Field(default_factory=_utc_now)
    data_hash: str = Field(..., description="SHA-256 hash of the raw API response payload")
    excerpt: str = Field(..., description="Relevant data excerpt for human readability")

    @staticmethod
    def compute_hash(payload: str | bytes) -> str:
        """Compute SHA-256 hash for citation integrity verification."""
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class AgentResult(BaseModel):
    """
    Structured output from a retriever agent.

    Contains the findings, citations, and metadata. The Supervisor
    validates that every claim in `findings` has a corresponding
    entry in `citations`.
    """

    result_id: str = Field(default_factory=_generate_id)
    task_id: str = Field(..., description="The TaskNode this result fulfills")
    session_id: str = Field(..., description="Parent session ID")
    agent_type: AgentType = Field(..., description="Which agent produced this result")
    pillar: PillarType = Field(..., description="Which pillar this result belongs to")
    findings: dict[str, Any] = Field(..., description="Structured findings specific to the pillar")
    citations: list[Citation] = Field(default_factory=list, min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0, description="Agent self-reported confidence")
    execution_time_ms: int = Field(..., ge=0, description="Wall-clock execution time in milliseconds")
    raw_api_response_url: str | None = Field(
        default=None,
        description="Blob Storage URL of the raw API response (for audit)",
    )
    created_at: datetime = Field(default_factory=_utc_now)


# ============================================================
# Validation & Conflict Models
# ============================================================


class ConflictDetail(BaseModel):
    """A detected cross-pillar conflict identified by the Supervisor."""

    conflict_type: str = Field(..., description="E.g., PATENT_MARKET_CONFLICT")
    pillars_involved: list[PillarType] = Field(..., min_length=2)
    description: str = Field(..., description="Human-readable conflict description")
    severity: ConflictSeverity = Field(...)
    recommendation: str = Field(..., description="Recommended action or escalation")


class ValidationResult(BaseModel):
    """
    Output of the Supervisor agent's grounding validation pass.

    If is_valid is False, the session cannot proceed to the Executor.
    Conflicts are always surfaced even if is_valid is True (as strategic risks).
    """

    is_valid: bool = Field(..., description="Whether all agent results passed grounding checks")
    conflicts: list[ConflictDetail] = Field(default_factory=list)
    grounding_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of claims with valid citations",
    )
    validation_notes: str = Field(default="", description="Additional notes from the Supervisor")
    validated_at: datetime = Field(default_factory=_utc_now)


# ============================================================
# Session Model (Top-Level Cosmos DB Document)
# ============================================================


class Session(BaseModel):
    """
    Top-level session document stored in Cosmos DB.

    This is the central state object for a query lifecycle.
    The Change Feed on this container triggers the Supervisor
    when all tasks reach COMPLETED status.
    """

    id: str = Field(default_factory=_generate_id, description="Session UUID (Cosmos DB partition key)")
    user_id: str = Field(..., description="Azure Entra ID object ID of the requesting user")
    query: str = Field(..., description="Original natural-language query")
    parameters: QueryParameters = Field(..., description="Structured query parameters")
    status: SessionStatus = Field(default=SessionStatus.PENDING)
    task_graph: list[TaskNode] = Field(default_factory=list)
    agent_results: list[AgentResult] = Field(default_factory=list)
    validation: ValidationResult | None = Field(default=None)
    decision: DecisionOutcome | None = Field(default=None)
    decision_rationale: str | None = Field(default=None)
    report_url: str | None = Field(default=None, description="Blob Storage URL for the PDF report")
    excel_url: str | None = Field(default=None, description="Blob Storage URL for the Excel workbook")
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = Field(default=None)


# ============================================================
# Service Bus Message Contract
# ============================================================


class ServiceBusMessage(BaseModel):
    """
    Contract for messages published to Azure Service Bus topics.

    The Planner publishes these; the Retriever agents consume them.
    """

    message_id: str = Field(default_factory=_generate_id)
    session_id: str = Field(...)
    task: TaskNode = Field(..., description="The task to be executed")
    correlation_id: str = Field(default_factory=_generate_id, description="OpenTelemetry trace correlation")
    published_at: datetime = Field(default_factory=_utc_now)


# ============================================================
# Audit Trail (21 CFR Part 11 Compliance)
# ============================================================


class AuditEntry(BaseModel):
    """
    Immutable audit log entry for regulatory compliance.

    Written to a separate Cosmos DB container with TTL = 7 years.
    Every agent action, API call, and LLM invocation MUST produce
    an AuditEntry.

    Compliance mapping:
      - 21 CFR Part 11 §11.10(e): Audit trail
      - EU GMP Annex 11 §9: Audit trail
    """

    entry_id: str = Field(default_factory=_generate_id)
    session_id: str = Field(...)
    timestamp: datetime = Field(default_factory=_utc_now, description="UTC, immutable once written")
    user_id: str = Field(..., description="Azure Entra ID object ID")
    agent_id: str = Field(..., description="Agent instance identifier")
    agent_type: AgentType = Field(...)
    action: AuditAction = Field(...)
    payload_hash: str = Field(..., description="SHA-256 hash of the action payload")
    details: dict[str, Any] = Field(default_factory=dict, description="Action-specific metadata")
    ip_address: str | None = Field(default=None)
    correlation_id: str | None = Field(default=None, description="OpenTelemetry trace ID")
