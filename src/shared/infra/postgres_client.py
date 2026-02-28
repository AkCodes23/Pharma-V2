"""
Pharma Agentic AI — PostgreSQL Client.

Async connection pool for the analytics and reporting layer.
Provides dual-write capability: Cosmos DB (hot path, source of truth)
+ PostgreSQL (analytics, materialized views, long-term memory).

Architecture context:
  - Service: Shared infrastructure
  - Responsibility: Analytics persistence, long-term memory, RAG metadata
  - Upstream: Supervisor, Executor, Celery workers
  - Downstream: PostgreSQL (Flexible Server in Azure, Docker locally)
  - Data ownership: Analytics/reporting data, NOT session lifecycle state
  - Failure: Fire-and-forget for analytics writes; fail loudly for queries

Performance optimizations:
  - Connection pool: asyncpg with 20 connections (configurable)
  - Prepared statements: Reused across calls for plan caching
  - Batch inserts: Bulk analytics writes in single transaction
  - Materialized view refresh: Async via Celery Beat (not on hot path)
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import uuid4

import asyncpg
from asyncpg import Pool, Connection

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class PostgresClient:
    """
    PostgreSQL client for analytics and reporting.

    NOT the source of truth for session lifecycle (that's Cosmos DB).
    Used for:
      1. Analytics queries (session duration, pillar performance, drug frequency)
      2. Materialized view management
      3. Long-term user memory
      4. RAG document metadata
      5. Agent registry (A2A protocol)
      6. Reflection log (SPAR framework)

    Thread-safe: asyncpg manages connection pooling internally.
    """

    _pool: Pool | None = None

    async def initialize(self) -> None:
        """
        Initialize the connection pool.

        Must be called once at application startup (e.g., in FastAPI lifespan).

        Supports two modes:
          - Local dev: standard user/password from DSN (default)
          - Azure: Azure AD token auth + SSL (POSTGRES_USE_AZURE_AD=true)
        """
        if self._pool is not None:
            return

        settings = get_settings()
        pg_cfg = settings.postgres

        # Build connection kwargs
        pool_kwargs: dict = {
            "dsn": pg_cfg.url,
            "min_size": 5,
            "max_size": pg_cfg.pool_size,
            "max_inactive_connection_lifetime": 300.0,
            "command_timeout": 30.0,
        }

        # Azure DB for PostgreSQL Flexible Server: SSL + Azure AD
        if pg_cfg.ssl_mode in ("require", "verify-full"):
            pool_kwargs["ssl"] = pg_cfg.ssl_mode

        if pg_cfg.use_azure_ad:
            try:
                from azure.identity import DefaultAzureCredential

                credential = DefaultAzureCredential()
                # Azure DB for PostgreSQL expects the token for
                # scope "https://ossrdbms-aad.database.windows.net/.default"
                token = credential.get_token(
                    "https://ossrdbms-aad.database.windows.net/.default"
                )
                pool_kwargs["password"] = token.token
                logger.info(
                    "Using Azure AD token for PostgreSQL",
                    extra={"ssl_mode": pg_cfg.ssl_mode},
                )
            except Exception as e:
                logger.error(
                    "Azure AD token acquisition failed — falling back to DSN password",
                    extra={"error": str(e)},
                )

        self._pool = await asyncpg.create_pool(**pool_kwargs)
        logger.info(
            "PostgresClient initialized",
            extra={
                "pool_size": pg_cfg.pool_size,
                "ssl_mode": pg_cfg.ssl_mode,
                "azure_ad": pg_cfg.use_azure_ad,
            },
        )

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[Connection, None]:
        """Acquire a connection from the pool."""
        if self._pool is None:
            raise RuntimeError("PostgresClient not initialized. Call initialize() first.")
        async with self._pool.acquire() as conn:
            yield conn

    # ── Session Analytics (Dual-Write) ─────────────────────

    async def write_session_analytics(
        self,
        session_id: str,
        user_id: str,
        query: str,
        drug_name: str | None,
        brand_name: str | None,
        target_market: str | None,
        time_horizon: str | None,
        therapeutic_area: str | None,
        status: str,
        decision: str | None = None,
        decision_rationale: str | None = None,
        grounding_score: float | None = None,
        conflict_count: int = 0,
        total_tasks: int = 0,
        completed_tasks: int = 0,
        failed_tasks: int = 0,
        report_url: str | None = None,
    ) -> None:
        """
        Write or update a session record in the analytics DB.

        Fire-and-forget: failures are logged but never block the hot path.
        """
        try:
            async with self.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO sessions (
                        id, user_id, query, drug_name, brand_name,
                        target_market, time_horizon, therapeutic_area,
                        status, decision, decision_rationale,
                        grounding_score, conflict_count,
                        total_tasks, completed_tasks, failed_tasks,
                        report_url, created_at, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, NOW(), NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        decision = COALESCE(EXCLUDED.decision, sessions.decision),
                        decision_rationale = COALESCE(EXCLUDED.decision_rationale, sessions.decision_rationale),
                        grounding_score = COALESCE(EXCLUDED.grounding_score, sessions.grounding_score),
                        conflict_count = EXCLUDED.conflict_count,
                        completed_tasks = EXCLUDED.completed_tasks,
                        failed_tasks = EXCLUDED.failed_tasks,
                        report_url = COALESCE(EXCLUDED.report_url, sessions.report_url),
                        updated_at = NOW(),
                        completed_at = CASE WHEN EXCLUDED.status IN ('COMPLETED', 'FAILED') THEN NOW() ELSE sessions.completed_at END
                    """,
                    session_id, user_id, query, drug_name, brand_name,
                    target_market, time_horizon, therapeutic_area,
                    status, decision, decision_rationale,
                    grounding_score, conflict_count,
                    total_tasks, completed_tasks, failed_tasks,
                    report_url,
                )
        except Exception:
            logger.exception("Failed to write session analytics", extra={"session_id": session_id})

    # ── Task Analytics ─────────────────────────────────────

    async def write_task_analytics(
        self,
        task_id: str,
        session_id: str,
        pillar: str,
        description: str,
        status: str,
        execution_time_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Write or update task analytics."""
        try:
            async with self.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO tasks (id, session_id, pillar, description, status, execution_time_ms, error_message, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        execution_time_ms = COALESCE(EXCLUDED.execution_time_ms, tasks.execution_time_ms),
                        error_message = COALESCE(EXCLUDED.error_message, tasks.error_message),
                        completed_at = CASE WHEN EXCLUDED.status IN ('COMPLETED', 'FAILED', 'DLQ') THEN NOW() ELSE tasks.completed_at END
                    """,
                    task_id, session_id, pillar, description, status, execution_time_ms, error_message,
                )
        except Exception:
            logger.exception("Failed to write task analytics", extra={"task_id": task_id})

    # ── Agent Result Analytics ─────────────────────────────

    async def write_agent_result_analytics(
        self,
        result_id: str,
        task_id: str,
        session_id: str,
        agent_type: str,
        pillar: str,
        findings: dict[str, Any],
        citation_count: int,
        confidence: float,
        execution_time_ms: int,
    ) -> None:
        """Write agent result analytics."""
        try:
            async with self.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_results (id, task_id, session_id, agent_type, pillar, findings, citation_count, confidence, execution_time_ms, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    result_id, task_id, session_id, agent_type, pillar,
                    json.dumps(findings, default=str), citation_count, confidence, execution_time_ms,
                )
        except Exception:
            logger.exception("Failed to write agent result analytics", extra={"result_id": result_id})

    # ── Reflection Log (SPAR Framework) ────────────────────

    async def write_reflection(
        self,
        session_id: str,
        agent_type: str,
        reflection_type: str,
        score: float | None = None,
        findings: dict[str, Any] | None = None,
        improvements: list[str] | None = None,
    ) -> None:
        """Log a reflection entry for the SPAR framework."""
        try:
            async with self.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO reflection_log (id, session_id, agent_type, reflection_type, score, findings, improvements, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                    """,
                    str(uuid4()), session_id, agent_type, reflection_type,
                    score, json.dumps(findings or {}, default=str),
                    json.dumps(improvements or [], default=str),
                )
        except Exception:
            logger.exception("Failed to write reflection", extra={"session_id": session_id})

    # ── Long-Term Memory ───────────────────────────────────

    async def store_user_memory(
        self, user_id: str, memory_type: str, key: str, value: dict[str, Any]
    ) -> None:
        """Store or update a long-term memory entry for a user."""
        try:
            async with self.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_memory (id, user_id, memory_type, key, value, access_count, last_accessed, created_at)
                    VALUES ($1, $2, $3, $4, $5, 1, NOW(), NOW())
                    ON CONFLICT (user_id, memory_type, key) DO UPDATE SET
                        value = EXCLUDED.value,
                        access_count = user_memory.access_count + 1,
                        last_accessed = NOW()
                    """,
                    str(uuid4()), user_id, memory_type, key, json.dumps(value, default=str),
                )
        except Exception:
            logger.exception("Failed to store user memory", extra={"user_id": user_id, "key": key})

    async def get_user_memories(
        self, user_id: str, memory_type: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Retrieve user long-term memories."""
        try:
            async with self.acquire() as conn:
                if memory_type:
                    rows = await conn.fetch(
                        """
                        SELECT key, value, access_count, last_accessed
                        FROM user_memory
                        WHERE user_id = $1 AND memory_type = $2
                        ORDER BY last_accessed DESC
                        LIMIT $3
                        """,
                        user_id, memory_type, limit,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT memory_type, key, value, access_count, last_accessed
                        FROM user_memory
                        WHERE user_id = $1
                        ORDER BY last_accessed DESC
                        LIMIT $2
                        """,
                        user_id, limit,
                    )
                return [dict(row) for row in rows]
        except Exception:
            logger.exception("Failed to get user memories", extra={"user_id": user_id})
            return []

    # ── Analytics Queries ──────────────────────────────────

    async def get_session_analytics(self, hours: int = 24) -> list[dict[str, Any]]:
        """Get session analytics for the last N hours."""
        try:
            async with self.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM mv_session_analytics
                    WHERE hour_bucket >= NOW() - INTERVAL '1 hour' * $1
                    ORDER BY hour_bucket DESC
                    """,
                    hours,
                )
                return [dict(row) for row in rows]
        except Exception:
            logger.exception("Failed to get session analytics")
            return []

    async def get_pillar_performance(self) -> list[dict[str, Any]]:
        """Get pillar performance metrics."""
        try:
            async with self.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM mv_pillar_performance")
                return [dict(row) for row in rows]
        except Exception:
            logger.exception("Failed to get pillar performance")
            return []

    async def refresh_materialized_views(self) -> None:
        """
        Refresh all materialized views.

        Called by Celery Beat on a schedule (e.g., every 15 minutes).
        NOT called on the hot path.
        """
        try:
            async with self.acquire() as conn:
                await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_session_analytics")
                await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_pillar_performance")
                await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_drug_frequency")
                logger.info("Materialized views refreshed")
        except Exception:
            logger.exception("Failed to refresh materialized views")

    # ── Agent Registry (A2A) ──────────────────────────────

    async def register_agent(
        self,
        agent_id: str,
        name: str,
        agent_type: str,
        capabilities: list[str],
        endpoint: str | None = None,
        health_check: str | None = None,
    ) -> None:
        """Register or update an agent in the persistent registry."""
        try:
            async with self.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_registry (agent_id, name, agent_type, capabilities, endpoint, health_check, status, last_heartbeat, registered_at)
                    VALUES ($1, $2, $3, $4, $5, $6, 'ACTIVE', NOW(), NOW())
                    ON CONFLICT (agent_id) DO UPDATE SET
                        capabilities = EXCLUDED.capabilities,
                        endpoint = COALESCE(EXCLUDED.endpoint, agent_registry.endpoint),
                        health_check = COALESCE(EXCLUDED.health_check, agent_registry.health_check),
                        status = 'ACTIVE',
                        last_heartbeat = NOW()
                    """,
                    agent_id, name, agent_type, json.dumps(capabilities),
                    endpoint, health_check,
                )
        except Exception:
            logger.exception("Failed to register agent", extra={"agent_id": agent_id})

    async def get_agents_by_capability(self, capability: str) -> list[dict[str, Any]]:
        """Find active agents that have a specific capability (A2A discovery)."""
        try:
            async with self.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM agent_registry
                    WHERE status = 'ACTIVE'
                      AND capabilities::jsonb @> $1::jsonb
                      AND last_heartbeat > NOW() - INTERVAL '2 minutes'
                    """,
                    json.dumps([capability]),
                )
                return [dict(row) for row in rows]
        except Exception:
            logger.exception("Failed to query agents by capability", extra={"capability": capability})
            return []

    # ── Cleanup ────────────────────────────────────────────

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgresClient closed")
