"""
Pharma Agentic AI — RAG Retriever.

Query-time RAG: embeds the query, runs hybrid search against
Azure AI Search, and formats results as LLM-ready context.

Architecture context:
  - Service: Shared RAG infrastructure
  - Responsibility: Query → relevant chunks → formatted context
  - Upstream: BaseRetriever._augment_with_rag(), MCP tool, Supervisor
  - Downstream: AISearchRAGClient (hybrid search), EmbeddingService
  - Failure: Returns empty context on search failure (agent proceeds without RAG)

Retrieval pattern:
  1. Embed query text (Azure OpenAI, cached)
  2. Run hybrid search (dense + BM25, semantic rerank)
  3. Apply minimum score threshold to filter low-quality results
  4. Format chunks into LLM context string with source citations
  5. Return RagContext(chunks, formatted_context, citations)

Hybrid search advantage:
  Dense only: misses drug name variants (e.g. "Ozempic" vs "semaglutide")
  BM25 only:  misses semantic matches ("weight loss drug" ≠ "obesity treatment")
  Hybrid:     BM25 catches exact terms, dense catches semantic, RRF merges.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.shared.infra.ai_search_client import get_ai_search_client
from src.shared.infra.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)

# Score thresholds - results below these are discarded as noise
SEMANTIC_SCORE_THRESHOLD = 2.0   # Azure semantic reranker score (0-4 scale)
VECTOR_SCORE_THRESHOLD = 0.65    # Cosine similarity (0-1 scale)


@dataclass
class RagChunk:
    """A single retrieved chunk with score information."""
    content: str
    source_id: str
    pillar: str
    drug_name: str
    score: float
    reranker_score: float | None = None
    citation_url: str = ""
    chunk_index: int = 0
    metadata_raw: str = ""


@dataclass
class RagContext:
    """
    Complete RAG result for a query.

    Passed to the LLM as augmented context. The `formatted_context`
    field is ready to insert directly into a system or user prompt.
    """
    chunks: list[RagChunk]
    formatted_context: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    total_retrieved: int = 0
    pillars_searched: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return len(self.chunks) == 0


class RagRetriever:
    """
    Query-time RAG retrieval for the pharma platform.

    Usage:
        retriever = RagRetriever()
        ctx = await retriever.retrieve(
            query="What Phase 3 trials exist for Semaglutide?",
            pillar="CLINICAL",
            drug_name="semaglutide",
            top_k=5,
        )
        if not ctx.is_empty:
            prompt = f"Use this context:\\n{ctx.formatted_context}\\n\\nQuestion: ..."
    """

    def __init__(self) -> None:
        self._search = get_ai_search_client()
        self._embedder = get_embedding_service()

    async def retrieve(
        self,
        query: str,
        pillar: str,
        drug_name: str = "",
        top_k: int = 5,
        session_filter: str = "",
        min_score: float | None = None,
    ) -> RagContext:
        """
        Retrieve relevant chunks for a query from a single pillar index.

        Args:
            query: Natural language query string.
            pillar: Target pillar (e.g. 'CLINICAL', 'LEGAL').
            drug_name: Optional drug name for metadata filtering.
            top_k: Max chunks to return.
            session_filter: Optional session_id to scope results.
            min_score: Override minimum score threshold.

        Returns:
            RagContext with chunks, formatted text, and citations.
        """
        if not query.strip():
            return _empty_context([pillar])

        try:
            query_vector = await self._embedder.embed(query)
        except Exception as e:
            logger.warning("RAG embed failed — returning empty context", extra={"error": str(e)})
            return _empty_context([pillar])

        try:
            raw_results = await self._search.hybrid_search(
                query_text=query,
                query_vector=query_vector,
                pillar=pillar,
                top_k=top_k,
                drug_name_filter=drug_name,
                session_filter=session_filter,
                use_semantic_ranker=True,
            )
        except Exception as e:
            logger.warning("RAG search failed — returning empty context", extra={"error": str(e)})
            return _empty_context([pillar])

        chunks = _filter_and_rank(raw_results, min_score)
        return _build_context(chunks, pillars=[pillar])

    async def retrieve_multi_pillar(
        self,
        query: str,
        pillars: list[str],
        drug_name: str = "",
        top_k_per_pillar: int = 3,
    ) -> RagContext:
        """
        Retrieve across multiple pillars concurrently and merge results.

        Useful for the Supervisor/Executor synthesising cross-pillar context.
        """
        if not query.strip() or not pillars:
            return _empty_context(pillars)

        try:
            query_vector = await self._embedder.embed(query)
        except Exception as e:
            logger.warning("RAG multi-pillar embed failed", extra={"error": str(e)})
            return _empty_context(pillars)

        try:
            raw_results = await self._search.multi_pillar_search(
                query_text=query,
                query_vector=query_vector,
                pillars=pillars,
                top_k_per_pillar=top_k_per_pillar,
                drug_name_filter=drug_name,
            )
        except Exception as e:
            logger.warning("RAG multi-pillar search failed", extra={"error": str(e)})
            return _empty_context(pillars)

        chunks = _filter_and_rank(raw_results, min_score=None)
        return _build_context(chunks, pillars=pillars)


# ── Helper functions ──────────────────────────────────────

def _filter_and_rank(
    raw_results: list[dict[str, Any]],
    min_score: float | None,
) -> list[RagChunk]:
    """Filter low-quality results and convert to RagChunk."""
    chunks: list[RagChunk] = []

    for r in raw_results:
        reranker = r.get("reranker_score")
        score = r.get("score", 0.0)

        # Apply score threshold
        effective_min = min_score
        if effective_min is None:
            effective_min = SEMANTIC_SCORE_THRESHOLD if reranker is not None else VECTOR_SCORE_THRESHOLD

        effective_score = reranker if reranker is not None else score
        if effective_score < effective_min:
            continue

        chunks.append(RagChunk(
            content=r.get("content", ""),
            source_id=r.get("source_id", ""),
            pillar=r.get("pillar", ""),
            drug_name=r.get("drug_name", ""),
            score=score,
            reranker_score=reranker,
            chunk_index=r.get("chunk_index", 0),
            metadata_raw=r.get("extra_metadata", ""),
        ))

    # Sort by best available score
    chunks.sort(
        key=lambda c: c.reranker_score if c.reranker_score is not None else c.score,
        reverse=True,
    )
    return chunks


def _build_context(chunks: list[RagChunk], pillars: list[str]) -> RagContext:
    """Format retrieved chunks into a structured LLM context string."""
    if not chunks:
        return _empty_context(pillars)

    parts: list[str] = ["=== Retrieved Knowledge ===\n"]
    citations: list[dict[str, Any]] = []

    for i, chunk in enumerate(chunks, 1):
        score_display = (
            f"reranker={chunk.reranker_score:.2f}"
            if chunk.reranker_score is not None
            else f"score={chunk.score:.3f}"
        )
        parts.append(f"[{i}] Source: {chunk.source_id} | Pillar: {chunk.pillar} | {score_display}")
        parts.append(chunk.content)
        parts.append("")

        citations.append({
            "index": i,
            "source_id": chunk.source_id,
            "pillar": chunk.pillar,
            "score": chunk.reranker_score or chunk.score,
        })

    parts.append("=== End Retrieved Knowledge ===")

    return RagContext(
        chunks=chunks,
        formatted_context="\n".join(parts),
        citations=citations,
        total_retrieved=len(chunks),
        pillars_searched=pillars,
    )


def _empty_context(pillars: list[str]) -> RagContext:
    return RagContext(
        chunks=[],
        formatted_context="",
        citations=[],
        total_retrieved=0,
        pillars_searched=pillars,
    )


# ── Module-level singleton ────────────────────────────────
_retriever: RagRetriever | None = None


def get_rag_retriever() -> RagRetriever:
    """Return shared RagRetriever singleton."""
    global _retriever
    if _retriever is None:
        _retriever = RagRetriever()
    return _retriever
