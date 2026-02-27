"""
Pharma Agentic AI — Enum Definitions.

Centralized enumerations used across all agents and infrastructure.
These enums enforce type-safe, deterministic state transitions
throughout the distributed agent swarm.
"""

from enum import StrEnum


class PillarType(StrEnum):
    """The four pillars of pharmaceutical strategic truth, plus internal knowledge."""

    LEGAL = "LEGAL"
    CLINICAL = "CLINICAL"
    COMMERCIAL = "COMMERCIAL"
    SOCIAL = "SOCIAL"
    KNOWLEDGE = "KNOWLEDGE"


class AgentType(StrEnum):
    """Agent roles within the distributed swarm."""

    PLANNER = "PLANNER"
    LEGAL_RETRIEVER = "LEGAL_RETRIEVER"
    CLINICAL_RETRIEVER = "CLINICAL_RETRIEVER"
    COMMERCIAL_RETRIEVER = "COMMERCIAL_RETRIEVER"
    SOCIAL_RETRIEVER = "SOCIAL_RETRIEVER"
    KNOWLEDGE_RETRIEVER = "KNOWLEDGE_RETRIEVER"
    SUPERVISOR = "SUPERVISOR"
    EXECUTOR = "EXECUTOR"


class SessionStatus(StrEnum):
    """Lifecycle states for a query session."""

    PENDING = "PENDING"
    PLANNING = "PLANNING"
    RETRIEVING = "RETRIEVING"
    VALIDATING = "VALIDATING"
    SYNTHESIZING = "SYNTHESIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"


class TaskStatus(StrEnum):
    """Lifecycle states for an individual retriever task."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    DLQ = "DLQ"


class DecisionOutcome(StrEnum):
    """Final strategic decision from the Executor."""

    GO = "GO"
    NO_GO = "NO_GO"
    CONDITIONAL_GO = "CONDITIONAL_GO"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ESCALATED = "ESCALATED"


class ConflictSeverity(StrEnum):
    """Severity of cross-pillar conflicts detected by the Supervisor."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AuditAction(StrEnum):
    """Enumeration of auditable actions for 21 CFR Part 11 compliance."""

    QUERY_SUBMITTED = "QUERY_SUBMITTED"
    SESSION_CREATED = "SESSION_CREATED"
    TASK_GRAPH_GENERATED = "TASK_GRAPH_GENERATED"
    TASK_PUBLISHED = "TASK_PUBLISHED"
    TASK_STARTED = "TASK_STARTED"
    DATA_RETRIEVED = "DATA_RETRIEVED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_RETRIED = "TASK_RETRIED"
    TASK_DLQ = "TASK_DLQ"
    VALIDATION_STARTED = "VALIDATION_STARTED"
    VALIDATION_PASSED = "VALIDATION_PASSED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    HITL_ESCALATED = "HITL_ESCALATED"
    REPORT_GENERATED = "REPORT_GENERATED"
    REPORT_DOWNLOADED = "REPORT_DOWNLOADED"
    SESSION_COMPLETED = "SESSION_COMPLETED"
    SESSION_FAILED = "SESSION_FAILED"
