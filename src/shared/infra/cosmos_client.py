"""
Pharma Agentic AI — Azure Cosmos DB Client.

Async wrapper for Azure Cosmos DB operations. Handles session
management, agent result persistence, and audit trail writes.

Architecture context:
  - Service: Shared infrastructure (used by ALL agents)
  - Responsibility: State management and persistence
  - Upstream: All agent services
  - Downstream: Azure Cosmos DB (NoSQL, Serverless)
  - Data ownership: Session lifecycle state, agent outputs, audit logs
  - Failure: Retries with exponential backoff; raises on exhaustion

Performance optimizations:
  - ETag-based optimistic concurrency on update_task_status (eliminates race conditions)
  - TTL for automatic session cleanup (30 days)
  - RU consumption tracking via response headers
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from azure.cosmos import ContainerProxy, CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.shared.config import get_settings
from src.shared.infra.cache_middleware import get_session_cache
from src.shared.models.enums import SessionStatus, TaskStatus
from src.shared.models.schemas import AgentResult, AuditEntry, Session, TaskNode, ValidationResult

logger = logging.getLogger(__name__)

# Default TTL for session documents: 30 days (auto-cleanup)
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 2,592,000 seconds


class CosmosDBClient:
    """
    Cosmos DB client for the Pharma Agentic AI platform.

    Manages two containers:
      - sessions: Query sessions with embedded task graphs and agent results
      - audit_trail: Immutable audit entries for 21 CFR Part 11 compliance

    Performance: Uses ETag-based optimistic concurrency on task status
    updates to eliminate the read-modify-write race condition when
    multiple agents complete concurrently.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = CosmosClient(
            url=settings.cosmos.endpoint,
            credential=settings.cosmos.key,
        )
        self._database = self._client.get_database_client(settings.cosmos.database_name)
        self._sessions = self._database.get_container_client(settings.cosmos.session_container)
        self._audit = self._database.get_container_client(settings.cosmos.audit_container)
        self._session_cache = get_session_cache()
        logger.info(
            "CosmosDBClient initialized",
            extra={"database": settings.cosmos.database_name},
        )

    def ensure_containers(self) -> None:
        """Create containers if they do not exist. Idempotent."""
        settings = get_settings()
        self._database.create_container_if_not_exists(
            id=settings.cosmos.session_container,
            partition_key=PartitionKey(path="/id"),
            default_ttl=SESSION_TTL_SECONDS,
        )
        self._database.create_container_if_not_exists(
            id=settings.cosmos.audit_container,
            partition_key=PartitionKey(path="/session_id"),
        )
        logger.info(
            "Cosmos DB containers verified/created",
            extra={"session_ttl_days": SESSION_TTL_SECONDS // 86400},
        )

    # ── Session Operations ────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception_type(CosmosHttpResponseError),
    )
    def create_session(self, session: Session) -> dict[str, Any]:
        """
        Create a new query session in Cosmos DB.

        Args:
            session: Validated Session model.

        Returns:
            The created Cosmos DB document (includes _etag).

        Raises:
            CosmosHttpResponseError: On persistent Cosmos DB failures.
        """
        doc = json.loads(session.model_dump_json())
        result = self._sessions.create_item(
            body=doc,
            populate_query_metrics=True,
        )
        self._session_cache.cache_session(session.id, doc)
        logger.info(
            "Session created",
            extra={"session_id": session.id, "status": session.status},
        )
        return result

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception_type(CosmosHttpResponseError),
    )
    def get_session(self, session_id: str) -> Session:
        """
        Retrieve a session by ID.

        Args:
            session_id: UUID of the session (also the partition key).

        Returns:
            Deserialized Session model.

        Raises:
            CosmosHttpResponseError: If session not found or DB error.
        """
        cached = self._session_cache.get_cached_session(session_id)
        if cached is not None:
            return Session.model_validate(cached)

        doc = self._sessions.read_item(item=session_id, partition_key=session_id)
        self._session_cache.cache_session(session_id, doc)
        return Session.model_validate(doc)

    def get_session_with_etag(self, session_id: str) -> tuple[Session, str]:
        """
        Retrieve a session with its ETag for optimistic concurrency.

        Returns:
            Tuple of (Session, etag_string).
        """
        doc = self._sessions.read_item(item=session_id, partition_key=session_id)
        etag = doc.get("_etag", "")
        return Session.model_validate(doc), etag

    def update_session_status(self, session_id: str, status: SessionStatus) -> None:
        """Update the status field of a session."""
        self._patch_session(session_id, [
            {"op": "replace", "path": "/status", "value": status.value},
            {"op": "replace", "path": "/updated_at", "value": datetime.now(timezone.utc).isoformat()},
        ])

    def add_task_to_session(self, session_id: str, task: TaskNode) -> None:
        """Append a task node to the session's task_graph."""
        task_doc = json.loads(task.model_dump_json())
        self._patch_session(session_id, [
            {"op": "add", "path": "/task_graph/-", "value": task_doc},
            {"op": "replace", "path": "/updated_at", "value": datetime.now(timezone.utc).isoformat()},
        ])

    def update_task_status(
        self,
        session_id: str,
        task_id: str,
        status: TaskStatus,
        error_message: str | None = None,
    ) -> None:
        """
        Update the status of a specific task within a session.

        Uses ETag-based optimistic concurrency to prevent lost updates
        when multiple agents complete concurrently.

        If a conflict occurs (another agent updated the session between
        our read and write), we retry with the fresh ETag (up to 3 times).

        Time complexity: O(T) where T = number of tasks in the session.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                session, etag = self.get_session_with_etag(session_id)

                for task in session.task_graph:
                    if task.task_id == task_id:
                        previous_status = task.status
                        task.status = status
                        if error_message:
                            task.error_message = error_message
                        if status == TaskStatus.RETRYING and previous_status != TaskStatus.RETRYING:
                            task.retry_count = min(task.retry_count + 1, 3)
                        if status == TaskStatus.COMPLETED:
                            task.completed_at = datetime.now(timezone.utc)
                        break

                session.updated_at = datetime.now(timezone.utc)
                doc = json.loads(session.model_dump_json())

                # Conditional write: only succeeds if ETag matches
                self._sessions.replace_item(
                    item=session_id,
                    body=doc,
                    etag=etag,
                    match_condition="IfMatch",
                )
                self._session_cache.invalidate(session_id)
                logger.info(
                    "Task status updated (optimistic concurrency)",
                    extra={
                        "session_id": session_id,
                        "task_id": task_id,
                        "status": status,
                        "attempt": attempt + 1,
                    },
                )
                return

            except CosmosHttpResponseError as e:
                if e.status_code == 412 and attempt < max_retries - 1:
                    # ETag mismatch — another agent updated concurrently
                    logger.warning(
                        "Optimistic concurrency conflict, retrying",
                        extra={
                            "session_id": session_id,
                            "task_id": task_id,
                            "attempt": attempt + 1,
                        },
                    )
                    continue
                raise

    def add_agent_result(self, session_id: str, result: AgentResult) -> None:
        """Append an agent result to the session."""
        result_doc = json.loads(result.model_dump_json())
        self._patch_session(session_id, [
            {"op": "add", "path": "/agent_results/-", "value": result_doc},
            {"op": "replace", "path": "/updated_at", "value": datetime.now(timezone.utc).isoformat()},
        ])

    def set_validation_result(self, session_id: str, validation: ValidationResult) -> None:
        """Set the Supervisor's validation result on the session."""
        val_doc = json.loads(validation.model_dump_json())
        self._patch_session(session_id, [
            {"op": "replace", "path": "/validation", "value": val_doc},
            {"op": "replace", "path": "/status", "value": SessionStatus.VALIDATING.value},
            {"op": "replace", "path": "/updated_at", "value": datetime.now(timezone.utc).isoformat()},
        ])

    def complete_session(
        self,
        session_id: str,
        decision: str,
        rationale: str,
        report_url: str | None = None,
        excel_url: str | None = None,
    ) -> None:
        """Mark a session as completed with final decision."""
        patches = [
            {"op": "replace", "path": "/status", "value": SessionStatus.COMPLETED.value},
            {"op": "replace", "path": "/decision", "value": decision},
            {"op": "replace", "path": "/decision_rationale", "value": rationale},
            {"op": "replace", "path": "/updated_at", "value": datetime.now(timezone.utc).isoformat()},
            {"op": "replace", "path": "/completed_at", "value": datetime.now(timezone.utc).isoformat()},
        ]
        if report_url:
            patches.append({"op": "replace", "path": "/report_url", "value": report_url})
        if excel_url:
            patches.append({"op": "replace", "path": "/excel_url", "value": excel_url})
        self._patch_session(session_id, patches)
        logger.info(
            "Session completed",
            extra={"session_id": session_id, "decision": decision},
        )

    # ── Audit Trail Operations ────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception_type(CosmosHttpResponseError),
    )
    def write_audit_entry(self, entry: AuditEntry) -> None:
        """
        Write an immutable audit entry to the audit_trail container.

        This operation is append-only. Audit entries are never modified
        or deleted (21 CFR Part 11 compliance).
        """
        doc = json.loads(entry.model_dump_json())
        self._audit.create_item(body=doc)
        logger.debug(
            "Audit entry written",
            extra={
                "session_id": entry.session_id,
                "action": entry.action,
                "agent_type": entry.agent_type,
            },
        )

    def write_audit_entries(self, entries: list[AuditEntry]) -> int:
        """
        Write multiple immutable audit entries.

        Attempts Cosmos item-batch operations grouped by partition key
        (session_id) and falls back to one-by-one writes when batch APIs
        are unavailable.
        """
        if not entries:
            return 0

        grouped: dict[str, list[AuditEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.session_id, []).append(entry)

        success_count = 0
        batch_method = getattr(self._audit, "execute_item_batch", None)

        for session_id, group in grouped.items():
            if callable(batch_method):
                docs = [json.loads(entry.model_dump_json()) for entry in group]
                operations = [("create", (doc,), {}) for doc in docs]
                try:
                    try:
                        batch_method(batch_operations=operations, partition_key=session_id)
                    except TypeError:
                        batch_method(operations, partition_key=session_id)
                    success_count += len(group)
                    continue
                except Exception:
                    logger.debug(
                        "Cosmos batch audit write unavailable; falling back to single-item writes",
                        extra={"session_id": session_id},
                        exc_info=True,
                    )

            for entry in group:
                try:
                    self.write_audit_entry(entry)
                    success_count += 1
                except Exception:
                    logger.exception(
                        "Failed to write audit entry",
                        extra={"session_id": entry.session_id, "entry_id": entry.entry_id},
                    )

        return success_count

    def query_audit_trail(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit entries for a given session."""
        query = "SELECT * FROM c WHERE c.session_id = @session_id ORDER BY c.timestamp ASC"
        items = list(
            self._audit.query_items(
                query=query,
                parameters=[{"name": "@session_id", "value": session_id}],
                max_item_count=limit,
            )
        )
        return [AuditEntry.model_validate(item) for item in items]

    # ── Change Feed (for Supervisor trigger) ──────────────────

    def get_sessions_container(self) -> ContainerProxy:
        """
        Return the raw ContainerProxy for the sessions container.

        Used by the Supervisor to set up Change Feed processing.
        """
        return self._sessions

    # ── Internal Helpers ──────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception_type(CosmosHttpResponseError),
    )
    def _patch_session(self, session_id: str, operations: list[dict[str, Any]]) -> None:
        """Apply partial update operations to a session document."""
        self._sessions.patch_item(
            item=session_id,
            partition_key=session_id,
            patch_operations=operations,
        )
        self._session_cache.invalidate(session_id)

    def list_sessions(
        self,
        *,
        drug_name: str = "",
        user_id: str = "",
        status: str = "",
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[Session], int]:
        """List sessions with optional filtering and pagination."""
        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        where_clauses: list[str] = []
        params: list[dict[str, Any]] = []

        if drug_name:
            where_clauses.append("CONTAINS(LOWER(c.parameters.drug_name), LOWER(@drug_name))")
            params.append({"name": "@drug_name", "value": drug_name})
        if user_id:
            where_clauses.append("c.user_id = @user_id")
            params.append({"name": "@user_id", "value": user_id})
        if status:
            where_clauses.append("c.status = @status")
            params.append({"name": "@status", "value": status})

        where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        count_query = f"SELECT VALUE COUNT(1) FROM c{where_sql}"
        total_items = list(
            self._sessions.query_items(
                query=count_query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
        total = int(total_items[0]) if total_items else 0

        page_query = (
            f"SELECT * FROM c{where_sql} "
            "ORDER BY c.created_at DESC "
            "OFFSET @offset LIMIT @limit"
        )
        page_params = params + [
            {"name": "@offset", "value": offset},
            {"name": "@limit", "value": limit},
        ]
        items = list(
            self._sessions.query_items(
                query=page_query,
                parameters=page_params,
                enable_cross_partition_query=True,
            )
        )
        sessions = [Session.model_validate(item) for item in items]
        return sessions, total

    def list_audit_entries(
        self,
        *,
        limit: int = 100,
        session_id: str = "",
    ) -> list[AuditEntry]:
        """List recent audit entries, optionally filtered by session."""
        limit = max(1, min(limit, 500))
        where_sql = " WHERE c.session_id = @session_id" if session_id else ""
        params = [{"name": "@session_id", "value": session_id}] if session_id else []
        query = f"SELECT TOP {limit} * FROM c{where_sql} ORDER BY c.timestamp DESC"

        items = list(
            self._audit.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
        return [AuditEntry.model_validate(item) for item in items]
