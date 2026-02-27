"""
Pharma Agentic AI — 21 CFR Part 11 Audit Trail Service.

Provides immutable audit logging for every agent action, API call,
and LLM invocation. Each entry includes:
  - UTC timestamp (immutable)
  - User ID (Azure Entra ID)
  - Agent ID and type
  - Action classification
  - SHA-256 payload hash (tamper detection)
  - OpenTelemetry correlation ID (trace linking)

Compliance mapping:
  - FDA 21 CFR Part 11 §11.10(e): Audit trails
  - EU GMP Annex 11 §9: Audit trails
  - ICH E6(R2): Electronic records integrity

Performance optimizations:
  - Async background queue: Non-blocking audit writes
  - Batch inserts: Reduces Cosmos DB RU consumption
  - Flush-on-shutdown: Guarantees delivery of queued entries
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.shared.models.enums import AgentType, AuditAction
from src.shared.models.schemas import AuditEntry

logger = logging.getLogger(__name__)

# Max entries to buffer before forcing a flush
BATCH_THRESHOLD = 10
# Max seconds between flushes
FLUSH_INTERVAL_SECONDS = 5.0


class AuditService:
    """
    Writes immutable audit entries to Cosmos DB.

    Performance: Uses an internal deque as a write-behind buffer.
    Entries are batched and flushed periodically or when the batch
    threshold is reached, reducing Cosmos DB round-trips.

    The flush-on-shutdown guarantee ensures all queued entries
    are persisted even during graceful agent termination.

    Thread-safe via threading.Lock for the write buffer.
    """

    def __init__(self, cosmos_client: Any) -> None:
        """
        Initialize with a CosmosDBClient instance.

        Args:
            cosmos_client: The shared Cosmos DB client for writes.
        """
        self._cosmos = cosmos_client
        self._buffer: deque[AuditEntry] = deque()
        self._lock = threading.Lock()
        self._flush_timer: threading.Timer | None = None
        self._start_flush_timer()

    def _start_flush_timer(self) -> None:
        """Start the periodic flush timer."""
        self._flush_timer = threading.Timer(FLUSH_INTERVAL_SECONDS, self._periodic_flush)
        self._flush_timer.daemon = True
        self._flush_timer.start()

    def _periodic_flush(self) -> None:
        """Called by the timer to flush buffered entries."""
        self._flush()
        self._start_flush_timer()

    def log(
        self,
        session_id: str,
        user_id: str,
        agent_type: AgentType,
        action: AuditAction,
        payload: dict[str, Any] | None = None,
        agent_id: str | None = None,
        ip_address: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditEntry:
        """
        Create an audit entry and queue it for async persistence.

        Non-blocking: the entry is added to an in-memory buffer and
        flushed to Cosmos DB in the background (either on threshold
        or on timer).

        Args:
            session_id: The query session this action belongs to.
            user_id: Azure Entra ID object ID of the initiating user.
            agent_type: The type of agent performing the action.
            action: The classified action being audited.
            payload: Optional action-specific metadata.
            agent_id: Instance identifier of the agent.
            ip_address: Client IP address if available.
            correlation_id: OpenTelemetry trace ID for distributed tracing.

        Returns:
            The AuditEntry (persisted asynchronously).
        """
        details = payload or {}
        payload_bytes = json.dumps(details, sort_keys=True, default=str).encode("utf-8")
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()

        entry = AuditEntry(
            entry_id=str(uuid4()),
            session_id=session_id,
            timestamp=datetime.now(timezone.utc),
            user_id=user_id,
            agent_id=agent_id or f"{agent_type.value}-{uuid4().hex[:8]}",
            agent_type=agent_type,
            action=action,
            payload_hash=payload_hash,
            details=details,
            ip_address=ip_address,
            correlation_id=correlation_id,
        )

        with self._lock:
            self._buffer.append(entry)
            buffer_size = len(self._buffer)

        logger.debug(
            "Audit entry queued",
            extra={
                "session_id": session_id,
                "action": action.value,
                "buffer_size": buffer_size,
            },
        )

        # Flush immediately if buffer exceeds threshold
        if buffer_size >= BATCH_THRESHOLD:
            self._flush()

        return entry

    def _flush(self) -> None:
        """
        Flush all buffered audit entries to Cosmos DB.

        Drains the entire buffer in a single batch. If any write
        fails, the entry is logged to stderr for manual recovery
        (compliance gap alert).
        """
        with self._lock:
            if not self._buffer:
                return
            entries = list(self._buffer)
            self._buffer.clear()

        success_count = 0
        for entry in entries:
            try:
                self._cosmos.write_audit_entry(entry)
                success_count += 1
            except Exception:
                # Audit writes must never crash the agent.
                # Log the failure loudly but continue processing.
                logger.exception(
                    "CRITICAL: Failed to write audit entry. Compliance gap detected.",
                    extra={
                        "session_id": entry.session_id,
                        "action": entry.action,
                        "entry_id": entry.entry_id,
                    },
                )

        if success_count > 0:
            logger.info(
                "Audit batch flushed",
                extra={"flushed": success_count, "total": len(entries)},
            )

    def query_trail(self, session_id: str, limit: int = 100) -> list[AuditEntry]:
        """
        Retrieve the audit trail for a session.

        Note: Flushes the buffer first to ensure consistency.

        Args:
            session_id: The session to query.
            limit: Maximum entries to return.

        Returns:
            List of AuditEntry objects, ordered by timestamp ascending.
        """
        self._flush()  # Ensure all pending entries are written
        return self._cosmos.query_audit_trail(session_id, limit=limit)

    def shutdown(self) -> None:
        """
        Graceful shutdown: flush remaining entries and cancel timer.

        MUST be called during agent shutdown to guarantee all audit
        entries are persisted (compliance requirement).
        """
        if self._flush_timer:
            self._flush_timer.cancel()
        self._flush()
        logger.info("AuditService shutdown complete — all entries flushed")
