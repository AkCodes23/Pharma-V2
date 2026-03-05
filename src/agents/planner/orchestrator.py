"""Planner-side orchestrator for standalone demo auto-progression."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from src.shared.config import get_settings
from src.shared.infra.redis_client import RedisClient
from src.shared.models.enums import SessionStatus, TaskStatus
from src.shared.ports.session_store import SessionStore

logger = logging.getLogger(__name__)


class PlannerOrchestrator:
    """Auto-runs validation and execution once retriever tasks are terminal."""

    def __init__(
        self,
        session_store: SessionStore,
        redis_client: RedisClient,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self._store = session_store
        self._redis = redis_client
        self._settings = get_settings()
        self._poll_interval_seconds = poll_interval_seconds
        self._http = httpx.AsyncClient(timeout=20.0)
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._local_locks: set[str] = set()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="planner-orchestrator")
        logger.info("Planner orchestrator started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._http.aclose()
        logger.info("Planner orchestrator stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                sessions, _ = await asyncio.to_thread(
                    self._store.list_sessions,
                    status=SessionStatus.RETRIEVING.value,
                    limit=200,
                    offset=0,
                )
                for session in sessions:
                    await self._maybe_orchestrate_session(session.id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Planner orchestrator loop iteration failed")

            await asyncio.sleep(self._poll_interval_seconds)

    async def _maybe_orchestrate_session(self, session_id: str) -> None:
        lock_key = f"orchestrate:{session_id}"
        if not self._acquire_lock(lock_key):
            return

        try:
            session = await asyncio.to_thread(self._store.get_session, session_id)
            terminal_states = {TaskStatus.COMPLETED, TaskStatus.DLQ, TaskStatus.FAILED}
            if not session.task_graph or not all(task.status in terminal_states for task in session.task_graph):
                self._release_lock(lock_key)
                return

            headers = self._build_internal_headers()

            supervisor_url = (
                f"{self._settings.provider.supervisor_url.rstrip('/')}/api/v1/sessions/{session_id}/validate"
            )
            validate_response = await self._http.post(supervisor_url, headers=headers)
            if validate_response.status_code >= 400:
                self._release_lock(lock_key)
                logger.error(
                    "Validation call failed",
                    extra={"session_id": session_id, "status_code": validate_response.status_code},
                )
                return

            validate_payload: dict[str, Any] = validate_response.json()
            if not bool(validate_payload.get("ready_for_execution", False)):
                self._release_lock(lock_key)
                return

            executor_url = (
                f"{self._settings.provider.executor_url.rstrip('/')}/api/v1/sessions/{session_id}/execute"
            )
            execute_response = await self._http.post(executor_url, headers=headers)
            if execute_response.status_code >= 400:
                self._release_lock(lock_key)
                logger.error(
                    "Execution call failed",
                    extra={"session_id": session_id, "status_code": execute_response.status_code},
                )
                return

            logger.info("Session auto-orchestration completed", extra={"session_id": session_id})

        except Exception:
            self._release_lock(lock_key)
            logger.exception("Failed to orchestrate session", extra={"session_id": session_id})

    def _build_internal_headers(self) -> dict[str, str]:
        api_key = os.getenv("PHARMA_INTERNAL_API_KEY", "")
        if not api_key:
            return {}
        return {"X-API-Key": api_key}

    def _acquire_lock(self, key: str) -> bool:
        try:
            acquired = self._redis.client.set(key, "1", ex=300, nx=True)
            return bool(acquired)
        except Exception:
            if key in self._local_locks:
                return False
            self._local_locks.add(key)
            return True

    def _release_lock(self, key: str) -> None:
        try:
            self._redis.client.delete(key)
        except Exception:
            self._local_locks.discard(key)
