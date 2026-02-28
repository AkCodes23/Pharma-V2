"""
Pharma Agentic AI — Knowledge Retriever: Azure AI Search Tools.

Internal RAG agent for hybrid search over company documents.
Wired to the real RAG pipeline (RagRetriever + Azure AI Search).

Architecture context:
  - Service: Knowledge Retriever Agent
  - Responsibility: Internal document search via RAG pipeline
  - Upstream: BaseRetriever dispatches task
  - Downstream: RagRetriever → EmbeddingService → AISearchRAGClient
  - Failure: Returns empty results with confidence=0 if RAG pipeline unavailable
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.shared.config import get_settings
from src.shared.models.schemas import Citation

logger = logging.getLogger(__name__)


def _hash(data: str) -> str:
    """Compute SHA-256 hash for citation integrity."""
    return hashlib.sha256(data.encode()).hexdigest()


def hybrid_search(
    query: str,
    top_k: int = 5,
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Execute a hybrid search (keyword + semantic) against Azure AI Search
    via the shared RAG pipeline.

    Uses RagRetriever.retrieve() which combines:
      - Dense vector search (embedding similarity)
      - BM25 keyword search
      - Semantic reranker (Azure AI Search)

    Falls back to empty results if the RAG infrastructure is unavailable
    (e.g., embedding service down, AI Search index not populated).

    Args:
        query: Natural-language search query.
        top_k: Number of top results to return.

    Returns:
        Tuple of (search_results, citation).
    """
    try:
        from src.shared.rag.rag_retriever import get_rag_retriever

        retriever = get_rag_retriever()

        # Run async retrieve in the event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If called from within an async context, use run_coroutine_threadsafe
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                rag_context = pool.submit(
                    asyncio.run,
                    retriever.retrieve(
                        query=query,
                        pillar="KNOWLEDGE",
                        top_k=top_k,
                    ),
                ).result(timeout=30)
        else:
            rag_context = loop.run_until_complete(
                retriever.retrieve(
                    query=query,
                    pillar="KNOWLEDGE",
                    top_k=top_k,
                )
            )

        if rag_context.is_empty:
            logger.info("RAG search returned no results", extra={"query": query[:80]})
            return _empty_result(query)

        # Convert RagChunk objects to serializable dicts
        results = []
        for chunk in rag_context.chunks:
            results.append({
                "document_id": chunk.source_id,
                "title": f"Internal Document — {chunk.pillar}",
                "content_snippet": chunk.content[:500],
                "relevance_score": chunk.reranker_score or chunk.score,
                "source": chunk.source_id,
                "pillar": chunk.pillar,
                "chunk_index": chunk.chunk_index,
                "data_source": "azure_ai_search",
            })

        raw = json.dumps(results, default=str)
        settings = get_settings()
        search_endpoint = settings.ai_search.endpoint if hasattr(settings, "ai_search") else "ai-search"

        citation = Citation(
            source_name="Azure AI Search (Internal Documents)",
            source_url=f"{search_endpoint}/indexes/pharma-internal-docs/docs/search",
            retrieved_at=datetime.now(timezone.utc),
            data_hash=_hash(raw),
            excerpt=f"Found {len(results)} internal documents for query: {query[:50]}...",
        )

        logger.info(
            "Knowledge RAG search completed",
            extra={"query": query[:80], "result_count": len(results)},
        )

        return results, citation

    except Exception as e:
        logger.warning(
            "RAG pipeline unavailable — returning empty results",
            extra={"query": query[:80], "error": str(e), "error_type": type(e).__name__},
        )
        return _empty_result(query)


def _empty_result(query: str) -> tuple[list[dict[str, Any]], Citation]:
    """Return empty results with explicit data-unavailable signal."""
    citation = Citation(
        source_name="Azure AI Search (Internal Documents) — Unavailable",
        source_url="",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash("empty"),
        excerpt=f"No internal documents found for: {query[:50]}...",
    )
    return [], citation
