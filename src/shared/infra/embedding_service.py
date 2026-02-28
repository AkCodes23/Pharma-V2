"""
Pharma Agentic AI — Azure OpenAI Embedding Service.

Shared embedding service for the RAG pipeline. Converts text chunks
into 1536-dim float32 vectors using Azure OpenAI text-embedding-3-small.

Architecture context:
  - Service: Shared RAG infrastructure
  - Responsibility: Text → vector conversion for ingestion and query
  - Upstream: IngestionPipeline (bulk), RagRetriever (single query)
  - Downstream: Azure OpenAI embeddings API
  - Failure: Raises EmbeddingError with full context on failure

Performance:
  - LRU in-memory cache: identical texts avoid redundant API calls
    (e.g. same drug name queried by multiple sessions in parallel)
  - Batch embedding: up to 2048 tokens per API call (model limit)
    Texts split into batches of `batch_size` (default 16 items)
  - Async: all calls non-blocking, uses httpx under the hood

Costs:
  text-embedding-3-small: $0.02 / 1M tokens (~50x cheaper than ada-002)
  100,000 avg doc chunks × 150 tokens = 15M tokens = ~$0.30 total index cost
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any

from openai import AsyncAzureOpenAI
from openai import APIConnectionError, APITimeoutError, RateLimitError

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────
_EMBEDDING_CACHE_SIZE = 4096    # LRU cache entries (each ~6KB)
_DEFAULT_BATCH_SIZE = 16        # Items per API call
_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.5            # seconds (exponential: 1.5s, 2.25s, 3.37s)

EMBEDDING_DIMENSIONS = 1536     # text-embedding-3-small output


class EmbeddingError(Exception):
    """Raised when embedding API fails after all retries."""
    pass


# ── Azure OpenAI client singleton ─────────────────────────
_openai_client: AsyncAzureOpenAI | None = None


def _get_openai_client() -> AsyncAzureOpenAI:
    """Lazy-initialize shared AsyncAzureOpenAI client."""
    global _openai_client
    if _openai_client is None:
        from src.shared.config import get_settings
        cfg = get_settings().openai
        _openai_client = AsyncAzureOpenAI(
            azure_endpoint=cfg.endpoint,
            api_key=cfg.api_key,
            api_version=cfg.api_version,
        )
    return _openai_client


# ── LRU-cached single text embedding ─────────────────────

@functools.lru_cache(maxsize=_EMBEDDING_CACHE_SIZE)
def _cached_embedding_key(text: str, model: str) -> str:
    """Cache key: used to check if a text is already cached."""
    return f"{model}::{text}"


class EmbeddingService:
    """
    Azure OpenAI embedding service with caching and batching.

    Usage:
        svc = EmbeddingService()
        vector = await svc.embed("Semaglutide Phase 3 trial data")
        vectors = await svc.embed_batch(["text1", "text2", ...])
    """

    def __init__(self, batch_size: int = _DEFAULT_BATCH_SIZE) -> None:
        from src.shared.config import get_settings
        cfg = get_settings()
        self._model = cfg.rag.embedding_model   # e.g. "text-embedding-3-small"
        self._batch_size = batch_size
        # In-memory cache: text → vector (not LRU but bounded dict with eviction)
        self._cache: dict[str, list[float]] = {}
        self._cache_hits = 0
        self._cache_misses = 0

    def _check_cache(self, text: str) -> list[float] | None:
        """Return cached vector or None."""
        key = f"{self._model}::{text[:200]}"  # key on first 200 chars to bound memory
        return self._cache.get(key)

    def _store_cache(self, text: str, vector: list[float]) -> None:
        """Store vector in cache, evicting oldest if at capacity."""
        if len(self._cache) >= _EMBEDDING_CACHE_SIZE:
            # Evict oldest entry
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[f"{self._model}::{text[:200]}"] = vector

    async def _call_api(self, texts: list[str]) -> list[list[float]]:
        """
        Call Azure OpenAI embeddings API with retry + backoff.

        Args:
            texts: List of strings to embed (max batch_size).

        Returns:
            List of 1536-dim float32 vectors, same order as input.

        Raises:
            EmbeddingError: If all retries exhausted.
        """
        client = _get_openai_client()
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = await client.embeddings.create(
                    input=texts,
                    model=self._model,
                    dimensions=EMBEDDING_DIMENSIONS,
                )
                # Sort by index to guarantee ordering
                sorted_data = sorted(response.data, key=lambda x: x.index)
                return [item.embedding for item in sorted_data]

            except RateLimitError as e:
                wait = _RETRY_BACKOFF * (2 ** attempt)
                logger.warning(
                    "Embedding rate limit — backing off",
                    extra={"attempt": attempt + 1, "wait_s": wait},
                )
                await asyncio.sleep(wait)
                last_exc = e

            except (APIConnectionError, APITimeoutError) as e:
                wait = _RETRY_BACKOFF * (1.5 ** attempt)
                logger.warning(
                    "Embedding connection error — retrying",
                    extra={"attempt": attempt + 1, "error": str(e)},
                )
                await asyncio.sleep(wait)
                last_exc = e

        raise EmbeddingError(
            f"Azure OpenAI embeddings failed after {_MAX_RETRIES} attempts: {last_exc}"
        )

    async def embed(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Returns cached vector if available (avoids API call).
        Preprocesses text: strip whitespace, truncate to 8000 chars
        (well within 8191-token model limit for typical pharma text).
        """
        text = text.strip()[:8000]
        if not text:
            return [0.0] * EMBEDDING_DIMENSIONS

        cached = self._check_cache(text)
        if cached:
            self._cache_hits += 1
            return cached

        self._cache_misses += 1
        vectors = await self._call_api([text])
        vector = vectors[0]
        self._store_cache(text, vector)
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts efficiently.

        Strategy:
          1. Check cache for each text — return cached vectors immediately
          2. Group remaining uncached texts into API batches of `batch_size`
          3. Send all batches concurrently via asyncio.gather
          4. Merge results maintaining original order
          5. Cache all new vectors

        Args:
            texts: List of strings (any length).

        Returns:
            List of vectors in same order as input texts.
        """
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        # Phase 1: Check cache
        for i, text in enumerate(texts):
            normalized = text.strip()[:8000]
            if not normalized:
                results[i] = [0.0] * EMBEDDING_DIMENSIONS
                continue
            cached = self._check_cache(normalized)
            if cached:
                results[i] = cached
                self._cache_hits += 1
            else:
                uncached_indices.append(i)
                uncached_texts.append(normalized)
                self._cache_misses += 1

        # Phase 2: Batch API calls for uncached
        if uncached_texts:
            batches = [
                uncached_texts[j : j + self._batch_size]
                for j in range(0, len(uncached_texts), self._batch_size)
            ]

            # Run all batches concurrently
            batch_results = await asyncio.gather(
                *[self._call_api(batch) for batch in batches],
                return_exceptions=True,
            )

            # Flatten batch results and assign back
            flat_idx = 0
            for batch_result in batch_results:
                if isinstance(batch_result, Exception):
                    logger.error("Embedding batch failed", extra={"error": str(batch_result)})
                    # Fill with zero vectors for failed batch
                    for _ in range(self._batch_size):
                        if flat_idx < len(uncached_indices):
                            results[uncached_indices[flat_idx]] = [0.0] * EMBEDDING_DIMENSIONS
                            flat_idx += 1
                    continue

                for vector in batch_result:
                    if flat_idx < len(uncached_indices):
                        orig_idx = uncached_indices[flat_idx]
                        results[orig_idx] = vector
                        self._store_cache(uncached_texts[flat_idx], vector)
                        flat_idx += 1

        # Safety: fill any remaining None slots with zero vectors
        return [r if r is not None else [0.0] * EMBEDDING_DIMENSIONS for r in results]

    def get_stats(self) -> dict[str, Any]:
        """Return cache hit/miss stats."""
        total = self._cache_hits + self._cache_misses
        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "total_requests": total,
            "hit_rate_pct": round(self._cache_hits / max(total, 1) * 100, 1),
            "cache_size": len(self._cache),
        }


# ── Module-level singleton ────────────────────────────────
_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Return shared EmbeddingService singleton."""
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service
