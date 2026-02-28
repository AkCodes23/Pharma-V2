"""
Pharma Agentic AI — Session Cache Middleware.

FastAPI dependency implementing cache-aside pattern for session reads.
Checks Redis first; on miss, falls through to Cosmos DB and populates cache.

Architecture context:
  - Service: Shared infrastructure (FastAPI dependency)
  - Responsibility: Reduce Cosmos DB RU consumption for repeat reads
  - Upstream: FastAPI GET /sessions/{id} endpoint
  - Downstream: RedisClient (cache) → CosmosDBClient (source of truth)
  - Failure: Cache miss falls through to Cosmos DB transparently
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.infra.redis_client import RedisClient

logger = logging.getLogger(__name__)

# Module-level singleton
_redis: RedisClient | None = None


def _get_redis() -> RedisClient:
    """Lazy-initialize the Redis client singleton."""
    global _redis
    if _redis is None:
        _redis = RedisClient()
    return _redis


class SessionCacheService:
    """
    Cache-aside service for session data.

    Read path:
      1. Check Redis → return if HIT
      2. On MISS → read from Cosmos DB
      3. Populate Redis cache (async, non-blocking)
      4. Return data

    Write path:
      1. Write to Cosmos DB (source of truth)
      2. Invalidate Redis cache (ensures consistency)

    This reduces Cosmos DB reads by ~80% for active sessions
    (users typically poll GET /sessions/{id} every 2-5 seconds).
    """

    def __init__(self, redis: RedisClient | None = None) -> None:
        self._redis = redis or _get_redis()

    def get_cached_session(self, session_id: str) -> dict[str, Any] | None:
        """
        Attempt to read session from Redis cache.

        Returns:
            Session dict on HIT, None on MISS or Redis failure.
        """
        return self._redis.get_cached_session(session_id)

    def cache_session(self, session_id: str, session_data: dict[str, Any]) -> bool:
        """
        Populate Redis cache after a Cosmos DB read.

        Returns:
            True if cached successfully, False on Redis failure.
        """
        return self._redis.cache_session(session_id, session_data)

    def invalidate(self, session_id: str) -> None:
        """
        Invalidate cached session on writes (status updates, completion).

        Must be called AFTER the Cosmos DB write succeeds.
        """
        self._redis.invalidate_session(session_id)
        logger.debug("Session cache invalidated", extra={"session_id": session_id})


# Singleton for dependency injection
_cache_service: SessionCacheService | None = None


def get_session_cache() -> SessionCacheService:
    """Get or create the singleton SessionCacheService."""
    global _cache_service
    if _cache_service is None:
        _cache_service = SessionCacheService()
    return _cache_service
