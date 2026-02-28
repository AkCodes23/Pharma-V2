"""
Unit tests for RedisClient — cache, rate limiting, dedup, circuit breaker.

Uses fakeredis to avoid needing a real Redis instance.
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

# We patch the redis.Redis constructor to return a fakeredis instance
try:
    import fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False


pytestmark = pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")


@pytest.fixture
def fake_redis():
    """Create a fakeredis instance for testing."""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def redis_client(fake_redis):
    """Create a RedisClient with a fake backend."""
    from src.shared.infra.redis_client import RedisClient

    client = RedisClient.__new__(RedisClient)
    client.client = fake_redis
    return client


class TestSessionCache:
    """Tests for session caching operations."""

    def test_cache_session_stores_and_retrieves(self, redis_client):
        """Cache write followed by read returns identical data."""
        session_data = {"session_id": "s-123", "status": "RUNNING", "query": "Keytruda"}
        assert redis_client.cache_session("s-123", session_data) is True

        cached = redis_client.get_cached_session("s-123")
        assert cached is not None
        assert cached["session_id"] == "s-123"
        assert cached["status"] == "RUNNING"

    def test_cache_miss_returns_none(self, redis_client):
        """Reading a non-existent key returns None."""
        assert redis_client.get_cached_session("nonexistent") is None

    def test_invalidate_session_removes_cache(self, redis_client):
        """Invalidation removes the cached entry."""
        redis_client.cache_session("s-456", {"status": "DONE"})
        redis_client.invalidate_session("s-456")
        assert redis_client.get_cached_session("s-456") is None


class TestRateLimiting:
    """Tests for sliding-window rate limiting."""

    def test_rate_limit_allows_under_limit(self, redis_client):
        """Requests under the limit are allowed."""
        allowed, remaining = redis_client.check_rate_limit("user-1", max_requests=5, window_seconds=60)
        assert allowed is True
        assert remaining == 4

    def test_rate_limit_blocks_at_limit(self, redis_client):
        """Requests at the limit are blocked."""
        for _ in range(5):
            redis_client.check_rate_limit("user-2", max_requests=5, window_seconds=60)

        allowed, remaining = redis_client.check_rate_limit("user-2", max_requests=5, window_seconds=60)
        assert allowed is False
        assert remaining == 0


class TestQueryDedup:
    """Tests for query deduplication."""

    def test_first_query_is_not_duplicate(self, redis_client):
        """First occurrence of a query is not a duplicate."""
        assert redis_client.is_duplicate_query("s-1", "What is Keytruda?") is False

    def test_same_query_is_duplicate(self, redis_client):
        """Same query within TTL window is detected as duplicate."""
        redis_client.is_duplicate_query("s-1", "What is Keytruda?")
        assert redis_client.is_duplicate_query("s-1", "What is Keytruda?") is True

    def test_different_query_is_not_duplicate(self, redis_client):
        """Different query text is not a duplicate."""
        redis_client.is_duplicate_query("s-1", "What is Keytruda?")
        assert redis_client.is_duplicate_query("s-1", "Patent expiry analysis") is False


class TestCircuitBreaker:
    """Tests for distributed circuit breaker."""

    def test_circuit_breaker_starts_closed(self, redis_client):
        """Circuit starts in CLOSED state."""
        assert redis_client.check_circuit_breaker("test-agent") is True

    def test_circuit_breaker_trips_after_failures(self, redis_client):
        """Circuit trips OPEN after threshold failures."""
        for _ in range(5):
            redis_client.record_circuit_failure("test-agent")

        assert redis_client.check_circuit_breaker("test-agent") is False
