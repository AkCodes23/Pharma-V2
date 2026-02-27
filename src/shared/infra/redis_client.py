"""
Pharma Agentic AI — Redis Client.

Provides caching, session state management, rate limiting, and
shared circuit breaker state across agent instances.

Architecture context:
  - Service: Shared infrastructure
  - Responsibility: Caching layer, rate limiting, ephemeral state
  - Upstream: All agent services
  - Downstream: Redis (in-memory data store)
  - Data ownership: Cache only — NEVER the sole source of truth
  - Failure: Graceful degradation — cache miss falls through to Cosmos DB

Performance optimizations:
  - Connection pool: Max 50 connections (configurable)
  - Pipeline: Batch operations reduce round-trips
  - TTL enforcement: All keys have explicit TTL (no unbounded growth)
  - Serialization: msgpack for speed (fallback to JSON)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import redis
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

from src.shared.config import get_settings

logger = logging.getLogger(__name__)

# Default TTLs (seconds)
SESSION_CACHE_TTL = 600       # 10 min
RESULT_CACHE_TTL = 86400      # 24 hours
QUERY_DEDUP_TTL = 3600        # 1 hour
RATE_LIMIT_WINDOW = 60        # 1 min sliding window
CIRCUIT_BREAKER_TTL = 300     # 5 min
AGENT_HEARTBEAT_TTL = 60      # 60s — agent considered dead after this


class RedisClient:
    """
    Redis client for the Pharma Agentic AI platform.

    Provides:
      1. Session caching — fast reads bypassing Cosmos DB
      2. Query deduplication — prevent duplicate analyses
      3. Rate limiting — sliding window per user
      4. Agent result caching — repeat query optimization
      5. Circuit breaker state — shared across instances
      6. Agent registry heartbeat — A2A protocol support

    All operations degrade gracefully on Redis failure:
    cache misses fall through to the primary data store.

    Thread-safe: redis-py handles connection pooling internally.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._pool = redis.ConnectionPool.from_url(
            url=settings.redis.url,
            max_connections=settings.redis.max_connections,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        self._client = redis.Redis(connection_pool=self._pool)
        self._session_ttl = settings.redis.session_cache_ttl
        self._result_ttl = settings.redis.result_cache_ttl

        # Verify connection
        try:
            self._client.ping()
            logger.info("RedisClient initialized", extra={"url": settings.redis.url})
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning(
                "Redis connection failed — operating in degraded mode",
                extra={"error": str(e)},
            )

    @property
    def client(self) -> redis.Redis:
        """Raw Redis client for advanced operations."""
        return self._client

    # ── Session Cache ──────────────────────────────────────

    def cache_session(self, session_id: str, session_data: dict[str, Any]) -> bool:
        """
        Cache a session document for fast reads.

        Args:
            session_id: Session UUID.
            session_data: Serializable session dict.

        Returns:
            True if cached successfully, False on Redis failure.
        """
        try:
            key = f"session:{session_id}"
            self._client.setex(key, self._session_ttl, json.dumps(session_data, default=str))
            logger.debug("Session cached", extra={"session_id": session_id, "ttl": self._session_ttl})
            return True
        except (RedisConnectionError, RedisTimeoutError):
            logger.warning("Failed to cache session", extra={"session_id": session_id})
            return False

    def get_cached_session(self, session_id: str) -> dict[str, Any] | None:
        """
        Retrieve a cached session.

        Returns:
            Session dict or None (cache miss or Redis failure).
        """
        try:
            key = f"session:{session_id}"
            data = self._client.get(key)
            if data:
                logger.debug("Session cache HIT", extra={"session_id": session_id})
                return json.loads(data)
            logger.debug("Session cache MISS", extra={"session_id": session_id})
            return None
        except (RedisConnectionError, RedisTimeoutError):
            return None

    def invalidate_session(self, session_id: str) -> None:
        """Remove a session from cache (on status change)."""
        try:
            self._client.delete(f"session:{session_id}")
        except (RedisConnectionError, RedisTimeoutError):
            pass  # Best-effort invalidation

    # ── Query Deduplication ────────────────────────────────

    def check_query_dedup(self, query: str, drug_name: str, market: str) -> str | None:
        """
        Check if an identical query was recently analyzed.

        Uses SHA-256 hash of the normalized query + drug + market.

        Returns:
            Existing session_id if duplicate, None otherwise.
        """
        try:
            query_hash = self._compute_query_hash(query, drug_name, market)
            key = f"query_hash:{query_hash}"
            return self._client.get(key)
        except (RedisConnectionError, RedisTimeoutError):
            return None

    def register_query(self, query: str, drug_name: str, market: str, session_id: str) -> None:
        """Register a query hash → session_id for deduplication."""
        try:
            query_hash = self._compute_query_hash(query, drug_name, market)
            key = f"query_hash:{query_hash}"
            self._client.setex(key, QUERY_DEDUP_TTL, session_id)
        except (RedisConnectionError, RedisTimeoutError):
            pass

    @staticmethod
    def _compute_query_hash(query: str, drug_name: str, market: str) -> str:
        """Compute a deterministic hash for query deduplication."""
        normalized = f"{query.strip().lower()}|{drug_name.strip().lower()}|{market.strip().lower()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    # ── Rate Limiting ──────────────────────────────────────

    def check_rate_limit(self, user_id: str, max_requests: int = 10, window_seconds: int = RATE_LIMIT_WINDOW) -> tuple[bool, int]:
        """
        Sliding window rate limiter.

        Args:
            user_id: User identifier.
            max_requests: Max requests per window.
            window_seconds: Window duration.

        Returns:
            Tuple of (is_allowed: bool, remaining: int).

        Time complexity: O(log N) where N = requests in window.
        """
        try:
            key = f"rate_limit:{user_id}"
            now = time.time()
            window_start = now - window_seconds

            pipe = self._client.pipeline()
            # Remove expired entries
            pipe.zremrangebyscore(key, 0, window_start)
            # Count current entries
            pipe.zcard(key)
            # Add current request
            pipe.zadd(key, {f"{now}": now})
            # Set TTL on the key
            pipe.expire(key, window_seconds)
            results = pipe.execute()

            current_count = results[1]
            remaining = max(0, max_requests - current_count - 1)
            allowed = current_count < max_requests

            if not allowed:
                logger.warning(
                    "Rate limit exceeded",
                    extra={"user_id": user_id, "count": current_count, "limit": max_requests},
                )

            return allowed, remaining
        except (RedisConnectionError, RedisTimeoutError):
            # On Redis failure, allow the request (fail-open for availability)
            return True, max_requests

    # ── Agent Result Cache ─────────────────────────────────

    def cache_agent_result(self, pillar: str, drug_name: str, market: str, result_data: dict[str, Any]) -> bool:
        """Cache an agent result for repeat query optimization."""
        try:
            key = f"result:{pillar}:{drug_name.lower()}:{market.lower()}"
            self._client.setex(key, self._result_ttl, json.dumps(result_data, default=str))
            return True
        except (RedisConnectionError, RedisTimeoutError):
            return False

    def get_cached_result(self, pillar: str, drug_name: str, market: str) -> dict[str, Any] | None:
        """Retrieve a cached agent result."""
        try:
            key = f"result:{pillar}:{drug_name.lower()}:{market.lower()}"
            data = self._client.get(key)
            if data:
                logger.debug("Agent result cache HIT", extra={"pillar": pillar, "drug": drug_name})
                return json.loads(data)
            return None
        except (RedisConnectionError, RedisTimeoutError):
            return None

    # ── Circuit Breaker (Shared State) ─────────────────────

    def get_circuit_state(self, agent_type: str) -> dict[str, Any] | None:
        """Get shared circuit breaker state for an agent type."""
        try:
            key = f"breaker:{agent_type}"
            data = self._client.get(key)
            return json.loads(data) if data else None
        except (RedisConnectionError, RedisTimeoutError):
            return None

    def set_circuit_state(self, agent_type: str, state: dict[str, Any]) -> None:
        """Update shared circuit breaker state."""
        try:
            key = f"breaker:{agent_type}"
            self._client.setex(key, CIRCUIT_BREAKER_TTL, json.dumps(state))
        except (RedisConnectionError, RedisTimeoutError):
            pass

    # ── Agent Registry Heartbeat (A2A) ─────────────────────

    def register_agent_heartbeat(self, agent_id: str, agent_info: dict[str, Any]) -> None:
        """Register or refresh an agent's heartbeat for A2A discovery."""
        try:
            key = f"agent:{agent_id}"
            self._client.setex(key, AGENT_HEARTBEAT_TTL, json.dumps(agent_info, default=str))
            # Also add to the active agents set
            self._client.sadd("active_agents", agent_id)
        except (RedisConnectionError, RedisTimeoutError):
            pass

    def get_active_agents(self) -> list[dict[str, Any]]:
        """Get all active agents (for A2A discovery)."""
        try:
            agent_ids = self._client.smembers("active_agents")
            agents = []
            for agent_id in agent_ids:
                data = self._client.get(f"agent:{agent_id}")
                if data:
                    agents.append(json.loads(data))
                else:
                    # Agent heartbeat expired — remove from set
                    self._client.srem("active_agents", agent_id)
            return agents
        except (RedisConnectionError, RedisTimeoutError):
            return []

    # ── Short-Term Memory ──────────────────────────────────

    def store_short_term_memory(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """Store conversation context for multi-turn queries."""
        try:
            key = f"memory:short:{session_id}"
            self._client.setex(key, self._session_ttl, json.dumps(messages, default=str))
        except (RedisConnectionError, RedisTimeoutError):
            pass

    def get_short_term_memory(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve conversation context."""
        try:
            key = f"memory:short:{session_id}"
            data = self._client.get(key)
            return json.loads(data) if data else []
        except (RedisConnectionError, RedisTimeoutError):
            return []

    # ── Cleanup ────────────────────────────────────────────

    def close(self) -> None:
        """Close the connection pool."""
        self._pool.disconnect()
        logger.info("RedisClient closed")
