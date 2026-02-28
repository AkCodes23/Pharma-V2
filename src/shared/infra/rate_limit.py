"""
Pharma Agentic AI — API Rate Limiting Middleware.

FastAPI dependency that enforces per-user rate limits using
the Redis sliding window rate limiter.

Architecture context:
  - Service: Shared infrastructure (FastAPI dependency)
  - Responsibility: Protect API from abuse, enforce fair usage
  - Upstream: FastAPI request pipeline (Depends())
  - Downstream: RedisClient.check_rate_limit()
  - Failure: Fail-open — if Redis is down, requests are allowed
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from src.shared.infra.redis_client import RedisClient

logger = logging.getLogger(__name__)

# Module-level singleton — initialized lazily
_redis: RedisClient | None = None


def _get_redis() -> RedisClient:
    """Lazy-initialize the Redis client singleton."""
    global _redis
    if _redis is None:
        _redis = RedisClient()
    return _redis


async def rate_limiter(request: Request) -> None:
    """
    FastAPI dependency: enforce per-user sliding window rate limit.

    Extracts user_id from:
      1. X-User-Id header (Azure API Management injects this)
      2. Falls back to client IP address

    Returns 429 Too Many Requests with Retry-After header on limit breach.

    Usage:
        @app.post("/api/v1/sessions", dependencies=[Depends(rate_limiter)])
        async def create_session(...):
            ...
    """
    # Explicit parentheses to avoid operator-precedence ambiguity:
    # `header or (host if client else "anonymous")`
    if request.client:
        user_id = request.headers.get("X-User-Id") or request.client.host
    else:
        user_id = request.headers.get("X-User-Id") or "anonymous"

    redis = _get_redis()
    allowed, remaining = redis.check_rate_limit(
        user_id=user_id,
        max_requests=10,
        window_seconds=60,
    )

    # Always set rate limit headers for client visibility
    request.state.rate_limit_remaining = remaining

    if not allowed:
        logger.warning(
            "Rate limit exceeded",
            extra={"user_id": user_id, "remaining": remaining},
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limit_exceeded",
                "message": "Too many requests. Please retry after 60 seconds.",
                "retry_after_seconds": 60,
            },
            headers={"Retry-After": "60"},
        )


RateLimited = Annotated[None, Depends(rate_limiter)]
