"""
Unit tests for Semantic LLM Cache.

Tests cache key computation, hit/miss behavior, stats tracking,
and the @llm_cached decorator.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

try:
    import fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

pytestmark = pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")


class TestCacheKeyComputation:
    """Tests for deterministic cache key generation."""

    def test_same_inputs_same_key(self):
        from src.shared.infra.llm_cache import compute_cache_key

        key1 = compute_cache_key("system", "user", "gpt-4o", 0.0)
        key2 = compute_cache_key("system", "user", "gpt-4o", 0.0)
        assert key1 == key2

    def test_different_inputs_different_key(self):
        from src.shared.infra.llm_cache import compute_cache_key

        key1 = compute_cache_key("system", "user_a", "gpt-4o", 0.0)
        key2 = compute_cache_key("system", "user_b", "gpt-4o", 0.0)
        assert key1 != key2

    def test_whitespace_normalization(self):
        from src.shared.infra.llm_cache import compute_cache_key

        key1 = compute_cache_key("  system  ", "  user  ", "gpt-4o", 0.0)
        key2 = compute_cache_key("system", "user", "gpt-4o", 0.0)
        assert key1 == key2

    def test_model_case_normalization(self):
        from src.shared.infra.llm_cache import compute_cache_key

        key1 = compute_cache_key("sys", "usr", "GPT-4o", 0.0)
        key2 = compute_cache_key("sys", "usr", "gpt-4o", 0.0)
        assert key1 == key2

    def test_temperature_rounding(self):
        from src.shared.infra.llm_cache import compute_cache_key

        key1 = compute_cache_key("sys", "usr", "m", 0.7000001)
        key2 = compute_cache_key("sys", "usr", "m", 0.70)
        assert key1 == key2


class TestCacheHitMiss:
    """Tests for cache get/set operations."""

    @pytest.fixture
    def mock_redis(self):
        fake = fakeredis.FakeRedis(decode_responses=True)
        mock_client = MagicMock()
        mock_client.client = fake
        return fake

    def test_cache_miss_returns_none(self, mock_redis):
        from src.shared.infra.llm_cache import get_cached_response

        with patch("src.shared.infra.llm_cache._get_redis") as m:
            m.return_value = MagicMock(client=mock_redis)
            result = get_cached_response("sys", "user", "model")
            assert result is None

    def test_cache_hit_returns_data(self, mock_redis):
        from src.shared.infra.llm_cache import cache_response, get_cached_response

        mock_obj = MagicMock(client=mock_redis)
        with patch("src.shared.infra.llm_cache._get_redis", return_value=mock_obj):
            cache_response("sys", "user", {"score": 0.9}, "model")
            result = get_cached_response("sys", "user", "model")
            assert result is not None
            assert result["score"] == 0.9


class TestCacheStats:
    """Tests for hit/miss statistics."""

    def test_stats_tracking(self):
        from src.shared.infra import llm_cache

        # Reset counters
        llm_cache._hit_count = 0
        llm_cache._miss_count = 0

        llm_cache._miss_count = 3
        llm_cache._hit_count = 7

        stats = llm_cache.get_cache_stats()
        assert stats["hits"] == 7
        assert stats["misses"] == 3
        assert stats["total"] == 10
        assert stats["hit_rate_pct"] == 70.0
