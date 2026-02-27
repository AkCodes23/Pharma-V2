"""
Pharma Agentic AI — Celery Tasks: Analytics.

Background tasks for materialized view refresh, stale session
cleanup, and agent health monitoring.

Architecture context:
  - Queue: pharma.analytics
  - Responsibility: Maintenance and monitoring tasks
  - Upstream: Celery Beat (periodic scheduler)
  - Downstream: PostgreSQL, Redis
"""

from __future__ import annotations

import logging

from src.shared.infra.celery_app import app

logger = logging.getLogger(__name__)


@app.task(
    name="src.shared.tasks.analytics_task.refresh_materialized_views",
    queue="pharma.analytics",
)
def refresh_materialized_views() -> dict:
    """
    Refresh PostgreSQL materialized views.

    Runs every 15 minutes via Celery Beat.
    Uses CONCURRENTLY to avoid locking reads.
    """
    import asyncio

    async def _refresh() -> None:
        from src.shared.infra.postgres_client import PostgresClient
        pg = PostgresClient()
        await pg.initialize()
        await pg.refresh_materialized_views()
        await pg.close()

    try:
        asyncio.run(_refresh())
        logger.info("Materialized views refreshed")
        return {"status": "success"}
    except Exception:
        logger.exception("Materialized view refresh failed")
        return {"status": "failed"}


@app.task(
    name="src.shared.tasks.analytics_task.cleanup_stale_sessions",
    queue="pharma.analytics",
)
def cleanup_stale_sessions() -> dict:
    """
    Clean up sessions stuck in PENDING/RETRIEVING for > 1 hour.

    Runs hourly via Celery Beat.
    Marks them as FAILED and logs to audit trail.
    """
    import asyncio

    async def _cleanup() -> int:
        from src.shared.infra.postgres_client import PostgresClient
        pg = PostgresClient()
        await pg.initialize()
        async with pg.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE sessions
                SET status = 'FAILED',
                    updated_at = NOW(),
                    completed_at = NOW()
                WHERE status IN ('PENDING', 'PLANNING', 'RETRIEVING')
                  AND created_at < NOW() - INTERVAL '1 hour'
                """
            )
            # Extract count from result string like "UPDATE 3"
            count = int(result.split()[-1]) if result else 0
        await pg.close()
        return count

    try:
        count = asyncio.run(_cleanup())
        if count > 0:
            logger.warning("Cleaned up stale sessions", extra={"count": count})
        return {"status": "success", "cleaned_up": count}
    except Exception:
        logger.exception("Stale session cleanup failed")
        return {"status": "failed"}


@app.task(
    name="src.shared.tasks.analytics_task.check_agent_health",
    queue="pharma.analytics",
)
def check_agent_health() -> dict:
    """
    Check health of all registered agents.

    Runs every 5 minutes via Celery Beat.
    Marks agents as INACTIVE if heartbeat expired.
    """
    import asyncio

    async def _check() -> int:
        from src.shared.infra.postgres_client import PostgresClient
        pg = PostgresClient()
        await pg.initialize()
        async with pg.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE agent_registry
                SET status = 'INACTIVE'
                WHERE status = 'ACTIVE'
                  AND last_heartbeat < NOW() - INTERVAL '2 minutes'
                """
            )
            count = int(result.split()[-1]) if result else 0
        await pg.close()
        return count

    try:
        inactive_count = asyncio.run(_check())
        if inactive_count > 0:
            logger.warning("Agents marked inactive", extra={"count": inactive_count})
        return {"status": "success", "inactive_agents": inactive_count}
    except Exception:
        logger.exception("Agent health check failed")
        return {"status": "failed"}
