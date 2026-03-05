from __future__ import annotations

from typing import Any, Protocol

from src.shared.models.enums import SessionStatus, TaskStatus
from src.shared.models.schemas import AgentResult, AuditEntry, Session, TaskNode, ValidationResult


class SessionStore(Protocol):
    """Persistence port for session and audit state."""

    def ensure_containers(self) -> None: ...

    def create_session(self, session: Session) -> dict[str, Any]: ...

    def get_session(self, session_id: str) -> Session: ...

    def get_session_with_etag(self, session_id: str) -> tuple[Session, str]: ...

    def update_session_status(self, session_id: str, status: SessionStatus) -> None: ...

    def add_task_to_session(self, session_id: str, task: TaskNode) -> None: ...

    def update_task_status(
        self,
        session_id: str,
        task_id: str,
        status: TaskStatus,
        error_message: str | None = None,
    ) -> None: ...

    def add_agent_result(self, session_id: str, result: AgentResult) -> None: ...

    def set_validation_result(self, session_id: str, validation: ValidationResult) -> None: ...

    def complete_session(
        self,
        session_id: str,
        decision: str,
        rationale: str,
        report_url: str | None = None,
        excel_url: str | None = None,
    ) -> None: ...

    def write_audit_entry(self, entry: AuditEntry) -> None: ...

    def write_audit_entries(self, entries: list[AuditEntry]) -> int: ...

    def query_audit_trail(self, session_id: str, limit: int = 100) -> list[AuditEntry]: ...

    def list_sessions(
        self,
        *,
        drug_name: str = "",
        user_id: str = "",
        status: str = "",
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[Session], int]: ...

    def list_audit_entries(self, *, limit: int = 100, session_id: str = "") -> list[AuditEntry]: ...
