from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

from src.shared.config import get_settings
from src.shared.models.enums import DecisionOutcome, SessionStatus, TaskStatus
from src.shared.models.schemas import AgentResult, AuditEntry, Session, TaskNode, ValidationResult
from src.shared.ports.session_store import SessionStore

logger = logging.getLogger(__name__)


class PostgresSessionStore(SessionStore):
    """PostgreSQL-backed store for demo mode session and audit state."""

    def __init__(self) -> None:
        self._dsn = get_settings().postgres.url
        self._pool: asyncpg.Pool | None = None

    def _run(self, coro: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=30)

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=self._dsn,
                    min_size=1,
                    max_size=10,
                    command_timeout=30,
                    timeout=10,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Unable to connect to PostgreSQL demo store. "
                    "Verify POSTGRES_URL and container readiness."
                ) from exc
        return self._pool

    async def _ensure_schema_async(self) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_sessions (
                    id TEXT PRIMARY KEY,
                    payload JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_demo_sessions_status
                ON demo_sessions ((payload->>'status'));
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_audit (
                    entry_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_demo_audit_session
                ON demo_audit (session_id, timestamp DESC);
                """
            )

    async def _fetch_session_payload(self, session_id: str) -> dict[str, Any]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload FROM demo_sessions WHERE id = $1",
                session_id,
            )
            if row is None:
                raise KeyError(f"Session not found: {session_id}")
            return dict(row["payload"])

    async def _store_session_payload(self, session_id: str, payload: dict[str, Any]) -> None:
        pool = await self._get_pool()
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO demo_sessions(id, payload, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (id) DO UPDATE
                SET payload = EXCLUDED.payload,
                    updated_at = EXCLUDED.updated_at
                """,
                session_id,
                json.dumps(payload, default=str),
            )

    def ensure_containers(self) -> None:
        self._run(self._ensure_schema_async())

    def create_session(self, session: Session) -> dict[str, Any]:
        payload = session.model_dump(mode="json")
        self._run(self._store_session_payload(session.id, payload))
        return payload

    def get_session(self, session_id: str) -> Session:
        payload = self._run(self._fetch_session_payload(session_id))
        return Session.model_validate(payload)

    def get_session_with_etag(self, session_id: str) -> tuple[Session, str]:
        payload = self._run(self._fetch_session_payload(session_id))
        etag = str(payload.get("updated_at", ""))
        return Session.model_validate(payload), etag

    def update_session_status(self, session_id: str, status: SessionStatus) -> None:
        session = self.get_session(session_id)
        session.status = status
        session.updated_at = datetime.now(timezone.utc)
        self._run(self._store_session_payload(session_id, session.model_dump(mode="json")))

    def add_task_to_session(self, session_id: str, task: TaskNode) -> None:
        session = self.get_session(session_id)
        session.task_graph.append(task)
        session.updated_at = datetime.now(timezone.utc)
        self._run(self._store_session_payload(session_id, session.model_dump(mode="json")))

    def update_task_status(
        self,
        session_id: str,
        task_id: str,
        status: TaskStatus,
        error_message: str | None = None,
    ) -> None:
        session = self.get_session(session_id)
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
        self._run(self._store_session_payload(session_id, session.model_dump(mode="json")))

    def add_agent_result(self, session_id: str, result: AgentResult) -> None:
        session = self.get_session(session_id)
        session.agent_results.append(result)
        session.updated_at = datetime.now(timezone.utc)
        self._run(self._store_session_payload(session_id, session.model_dump(mode="json")))

    def set_validation_result(self, session_id: str, validation: ValidationResult) -> None:
        session = self.get_session(session_id)
        session.validation = validation
        session.status = SessionStatus.VALIDATING
        session.updated_at = datetime.now(timezone.utc)
        self._run(self._store_session_payload(session_id, session.model_dump(mode="json")))

    def complete_session(
        self,
        session_id: str,
        decision: str,
        rationale: str,
        report_url: str | None = None,
        excel_url: str | None = None,
    ) -> None:
        session = self.get_session(session_id)
        session.status = SessionStatus.COMPLETED
        session.decision = DecisionOutcome(decision)
        session.decision_rationale = rationale
        session.report_url = report_url
        session.excel_url = excel_url
        session.updated_at = datetime.now(timezone.utc)
        session.completed_at = datetime.now(timezone.utc)
        self._run(self._store_session_payload(session_id, session.model_dump(mode="json")))

    async def _write_audit_entry_async(self, entry: AuditEntry) -> None:
        pool = await self._get_pool()
        payload = entry.model_dump(mode="json")
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO demo_audit(entry_id, session_id, payload, timestamp)
                VALUES ($1, $2, $3::jsonb, $4)
                ON CONFLICT (entry_id) DO NOTHING
                """,
                entry.entry_id,
                entry.session_id,
                json.dumps(payload, default=str),
                entry.timestamp,
            )

    def write_audit_entry(self, entry: AuditEntry) -> None:
        self._run(self._write_audit_entry_async(entry))

    async def _write_audit_entries_async(self, entries: list[AuditEntry]) -> int:
        if not entries:
            return 0
        pool = await self._get_pool()
        rows = [
            (
                e.entry_id,
                e.session_id,
                json.dumps(e.model_dump(mode="json"), default=str),
                e.timestamp,
            )
            for e in entries
        ]
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO demo_audit(entry_id, session_id, payload, timestamp)
                VALUES ($1, $2, $3::jsonb, $4)
                ON CONFLICT (entry_id) DO NOTHING
                """,
                rows,
            )
        return len(entries)

    def write_audit_entries(self, entries: list[AuditEntry]) -> int:
        return int(self._run(self._write_audit_entries_async(entries)))

    async def _query_audit_async(self, session_id: str, limit: int) -> list[AuditEntry]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload
                FROM demo_audit
                WHERE session_id = $1
                ORDER BY timestamp ASC
                LIMIT $2
                """,
                session_id,
                max(1, min(limit, 500)),
            )
        return [AuditEntry.model_validate(dict(row["payload"])) for row in rows]

    def query_audit_trail(self, session_id: str, limit: int = 100) -> list[AuditEntry]:
        return self._run(self._query_audit_async(session_id, limit))

    def list_sessions(
        self,
        *,
        drug_name: str = "",
        user_id: str = "",
        status: str = "",
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[Session], int]:
        async def _list() -> tuple[list[Session], int]:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT payload FROM demo_sessions")
            sessions = [Session.model_validate(dict(row["payload"])) for row in rows]

            if drug_name:
                needle = drug_name.lower()
                sessions = [s for s in sessions if needle in (s.parameters.drug_name or "").lower()]
            if user_id:
                sessions = [s for s in sessions if s.user_id == user_id]
            if status:
                status_upper = status.upper()
                sessions = [s for s in sessions if s.status.value == status_upper]

            sessions.sort(key=lambda s: s.created_at, reverse=True)
            total = len(sessions)
            page = sessions[offset : offset + max(1, min(limit, 100))]
            return page, total

        return self._run(_list())

    def list_audit_entries(self, *, limit: int = 100, session_id: str = "") -> list[AuditEntry]:
        async def _list() -> list[AuditEntry]:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                if session_id:
                    rows = await conn.fetch(
                        """
                        SELECT payload FROM demo_audit
                        WHERE session_id = $1
                        ORDER BY timestamp DESC
                        LIMIT $2
                        """,
                        session_id,
                        max(1, min(limit, 500)),
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT payload FROM demo_audit
                        ORDER BY timestamp DESC
                        LIMIT $1
                        """,
                        max(1, min(limit, 500)),
                    )
            return [AuditEntry.model_validate(dict(row["payload"])) for row in rows]

        return self._run(_list())
