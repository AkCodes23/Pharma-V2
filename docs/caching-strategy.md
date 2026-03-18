# Caching Strategy Guide

This document captures the cache layers used by the platform and production recommendations for Azure.

## 1. Cache Layers

Primary cache-related components:

- Session cache middleware: `src/shared/infra/cache_middleware.py`
- LLM/result cache utility: `src/shared/infra/llm_cache.py`
- Redis client: `src/shared/infra/redis_client.py`

## 2. Session Cache Pattern

Session polling endpoints can use cache-first read-through behavior:

1. Attempt Redis read by session key.
2. On miss, load from Cosmos DB.
3. Store serialized session payload in Redis with TTL.

Benefits:

- reduced Cosmos read pressure,
- lower p95 read latency,
- improved dashboard responsiveness.

## 3. Cache Key Design

Use deterministic keys that include:

- entity type (`session`, `llm`, etc.),
- stable identifier (session_id or query hash),
- optional scope/version suffix for schema evolution.

Do not include secrets or raw auth tokens in cache keys/values.

## 4. TTL and Invalidation

Recommended production posture:

- Session cache: short TTL (minutes) for near-real-time state
- Derived/LLM cache: longer TTL (hours) when staleness is acceptable
- Invalidate on write/update paths to avoid stale decision views

If uncertain, bias toward freshness for compliance-critical decisions.

## 5. Azure Redis Guidance

- Use Azure Cache for Redis with TLS enabled.
- Restrict public network access where possible.
- Track memory pressure, eviction, and command latency.
- Set alerts for sustained low hit-rate and high evictions.

## 6. Failure Handling

Cache failures must fail safe:

- read failure → fallback to authoritative store,
- write failure → continue request path,
- never block session completion solely due to cache outage.

## 7. Observability

Track:

- cache hit/miss ratio,
- session endpoint latency with/without cache,
- Redis error rate,
- staleness incidents from delayed invalidation.
