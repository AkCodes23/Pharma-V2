"""
Pharma Agentic AI — Azure AI Search Client.

Production RAG vector store backed by Azure AI Search.
Supports hybrid retrieval (dense vectors + BM25 keyword), semantic
ranking, and per-pillar index isolation.

Architecture context:
  - Service: Shared RAG infrastructure
  - Responsibility: Vector index management and hybrid search
  - Upstream: IngestionPipeline (writes), RagRetriever (reads)
  - Downstream: Azure AI Search REST API
  - Failure: Graceful degradation — search failure logs warning, returns []
  - Security: API key via Azure Key Vault (env: AI_SEARCH_API_KEY)

Index design:
  One index per pharma pillar so searches are isolated by domain:
    pharma-legal, pharma-clinical, pharma-commercial,
    pharma-social, pharma-knowledge, pharma-news, pharma-sessions

Each document in the index has:
  - id           : SHA-256 hash of (source_id + chunk_index) — idempotent upsert
  - content      : Chunk text
  - content_vector: 1536-dim float32 from text-embedding-3-small
  - source_id    : Original document identifier (URL, NDA number, etc.)
  - pillar       : PillarType string
  - drug_name    : Normalized drug name for metadata filter
  - session_id   : Source session (optional)
  - chunk_index  : Position within original document
  - total_chunks : Total chunks in original document
  - ingested_at  : ISO8601 timestamp

Performance:
  - Shared SearchClient per index (connection pool reused)
  - Hybrid query: VectorQuery (dense) + SearchQuery (BM25 keyword) merged by RRF
  - Semantic reranker profile applied post-hybrid for cross-encoder quality
  - Batch upsert: 1000 docs per API call (AI Search limit)
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError, ServiceRequestError
from azure.search.documents import SearchClient
from azure.search.documents.aio import SearchClient as AsyncSearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────
VECTOR_DIMENSIONS = 1536          # text-embedding-3-small output size
HNSW_M = 4                        # HNSW graph degree (trade-off: quality vs memory)
HNSW_EF_CONSTRUCTION = 400        # Build-time HNSW quality
MAX_BATCH_UPSERT = 1000           # Azure AI Search limit per batch
SEMANTIC_CONFIG_NAME = "pharma-semantic"
VECTOR_PROFILE_NAME = "pharma-vector-hnsw"

# Pillar → index name mapping
PILLAR_INDEXES: dict[str, str] = {
    "LEGAL":      "pharma-legal",
    "CLINICAL":   "pharma-clinical",
    "COMMERCIAL": "pharma-commercial",
    "SOCIAL":     "pharma-social",
    "KNOWLEDGE":  "pharma-knowledge",
    "NEWS":       "pharma-news",
    "SESSIONS":   "pharma-sessions",
}


# ── Document schema ───────────────────────────────────────

def _make_doc_id(source_id: str, chunk_index: int) -> str:
    """
    Deterministic document ID from source + chunk position.
    SHA-256 truncated to 32 hex chars — safe for Azure Search IDs.
    Re-ingesting the same chunk produces the same ID → idempotent upsert.
    """
    raw = f"{source_id}::chunk::{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _build_search_document(
    source_id: str,
    chunk_index: int,
    total_chunks: int,
    content: str,
    vector: list[float],
    pillar: str,
    drug_name: str,
    session_id: str = "",
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a document dict ready for Azure AI Search upsert."""
    doc: dict[str, Any] = {
        "id": _make_doc_id(source_id, chunk_index),
        "content": content,
        "content_vector": vector,
        "source_id": source_id,
        "pillar": pillar.upper(),
        "drug_name": drug_name.lower().strip(),
        "session_id": session_id,
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra_metadata:
        # Store flattened extra metadata as JSON string (AI Search doesn't support nested objects)
        import json
        doc["extra_metadata"] = json.dumps(extra_metadata, default=str)[:4096]
    return doc


# ── Index schema builder ──────────────────────────────────

def _build_index_schema(index_name: str) -> SearchIndex:
    """
    Build the Azure AI Search index schema with:
    - Full-text search (BM25) on `content`
    - Vector HNSW index on `content_vector` (1536-dim)
    - Metadata filterable fields (pillar, drug_name, session_id)
    - Semantic ranking config pointing to `content` as primary field
    """
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True,
                    filterable=True, sortable=True),
        SearchableField(name="content", type=SearchFieldDataType.String,
                        analyzer_name="en.microsoft"),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=VECTOR_DIMENSIONS,
            vector_search_profile_name=VECTOR_PROFILE_NAME,
        ),
        SimpleField(name="source_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="pillar", type=SearchFieldDataType.String,
                    filterable=True, facetable=True),
        SimpleField(name="drug_name", type=SearchFieldDataType.String,
                    filterable=True, facetable=True),
        SimpleField(name="session_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="chunk_index", type=SearchFieldDataType.Int32, sortable=True),
        SimpleField(name="total_chunks", type=SearchFieldDataType.Int32),
        SimpleField(name="ingested_at", type=SearchFieldDataType.DateTimeOffset,
                    filterable=True, sortable=True),
        SimpleField(name="extra_metadata", type=SearchFieldDataType.String),
    ]

    vector_search = VectorSearch(
        profiles=[VectorSearchProfile(name=VECTOR_PROFILE_NAME,
                                       algorithm_configuration_name="pharma-hnsw")],
        algorithms=[HnswAlgorithmConfiguration(
            name="pharma-hnsw",
            parameters={
                "m": HNSW_M,
                "efConstruction": HNSW_EF_CONSTRUCTION,
                "efSearch": 500,
                "metric": "cosine",
            },
        )],
    )

    semantic_search = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIG_NAME,
                prioritized_fields=SemanticPrioritizedFields(
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ]
    )

    return SearchIndex(
        name=index_name,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search,
    )


# ── Azure AI Search Client ────────────────────────────────

class AISearchRAGClient:
    """
    Azure AI Search client for Pharma RAG pipeline.

    Manages:
      - Index creation/verification on startup
      - Batch document upsert (idempotent via deterministic IDs)
      - Hybrid search (dense vector + BM25) with semantic reranking
      - Per-pillar index isolation (no cross-pillar contamination)

    Usage:
        client = AISearchRAGClient()
        await client.initialize()  # ensures all indexes exist

        # Ingestion
        await client.upsert_chunks(chunks, pillar="LEGAL")

        # Retrieval
        results = await client.hybrid_search("Semaglutide Phase 3", "CLINICAL", top_k=5)
    """

    def __init__(self) -> None:
        from src.shared.config import get_settings
        cfg = get_settings().search

        self._endpoint = cfg.endpoint
        self._credential = AzureKeyCredential(cfg.api_key)
        self._index_client = SearchIndexClient(
            endpoint=self._endpoint,
            credential=self._credential,
        )
        # Lazy per-index search clients (created on first use)
        self._search_clients: dict[str, AsyncSearchClient] = {}

    def _get_search_client(self, index_name: str) -> AsyncSearchClient:
        """Get or create async search client for an index (connection pooling)."""
        if index_name not in self._search_clients:
            self._search_clients[index_name] = AsyncSearchClient(
                endpoint=self._endpoint,
                index_name=index_name,
                credential=self._credential,
            )
        return self._search_clients[index_name]

    async def initialize(self) -> None:
        """
        Ensure all pharma pillar indexes exist. Creates them if missing.
        Safe to call on every startup — no-op if index already exists.
        """
        existing = {idx.name for idx in self._index_client.list_indexes()}
        created = []

        for pillar, index_name in PILLAR_INDEXES.items():
            if index_name not in existing:
                schema = _build_index_schema(index_name)
                self._index_client.create_index(schema)
                created.append(index_name)
                logger.info("Created AI Search index", extra={"index": index_name, "pillar": pillar})

        if created:
            logger.info("AI Search indexes created", extra={"count": len(created), "indexes": created})
        else:
            logger.info("All AI Search indexes already exist")

    async def upsert_chunks(
        self,
        chunks: list[dict[str, Any]],
        pillar: str,
    ) -> int:
        """
        Upsert a batch of chunk documents into the pillar index.

        Args:
            chunks: List of dicts from `_build_search_document()`.
            pillar: Pillar key (e.g. 'LEGAL').

        Returns:
            Number of documents successfully upserted.

        Notes:
            - Idempotent: same chunk_id → merge_or_upload (no duplicates)
            - Batches of 1000 (Azure Search limit per request)
            - Failures are logged per-batch but don't raise (fail-open)
        """
        index_name = PILLAR_INDEXES.get(pillar.upper())
        if not index_name:
            logger.warning("Unknown pillar for AI Search upsert", extra={"pillar": pillar})
            return 0

        client = self._get_search_client(index_name)
        total_upserted = 0

        # Batch in groups of MAX_BATCH_UPSERT
        for i in range(0, len(chunks), MAX_BATCH_UPSERT):
            batch = chunks[i : i + MAX_BATCH_UPSERT]
            try:
                results = await client.merge_or_upload_documents(documents=batch)
                succeeded = sum(1 for r in results if r.succeeded)
                total_upserted += succeeded
                logger.info(
                    "AI Search batch upsert",
                    extra={"index": index_name, "batch": i // MAX_BATCH_UPSERT + 1,
                           "succeeded": succeeded, "total_in_batch": len(batch)},
                )
            except (HttpResponseError, ServiceRequestError) as e:
                logger.error(
                    "AI Search upsert batch failed — skipping batch",
                    extra={"index": index_name, "error": str(e), "batch_size": len(batch)},
                )

        return total_upserted

    async def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float],
        pillar: str,
        top_k: int = 5,
        drug_name_filter: str = "",
        session_filter: str = "",
        use_semantic_ranker: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Hybrid search combining dense vector similarity and BM25 keyword ranking.

        Result fusion: Azure AI Search uses Reciprocal Rank Fusion (RRF) to
        blend vector and keyword scores before semantic reranking is applied.

        Args:
            query_text: Natural language query for BM25 keyword search.
            query_vector: 1536-dim float32 embedding of query_text.
            pillar: Target pillar index.
            top_k: Number of results to return.
            drug_name_filter: Optional exact drug name filter.
            session_filter: Optional session_id filter.
            use_semantic_ranker: Apply Azure semantic reranker (L2 rerank).

        Returns:
            List of result dicts: {content, score, source_id, drug_name,
                                   chunk_index, pillar, extra_metadata}
        """
        index_name = PILLAR_INDEXES.get(pillar.upper())
        if not index_name:
            logger.warning("Unknown pillar for AI Search query", extra={"pillar": pillar})
            return []

        # Build OData filter
        filters: list[str] = []
        if drug_name_filter:
            safe_name = drug_name_filter.lower().replace("'", "''")
            filters.append(f"drug_name eq '{safe_name}'")
        if session_filter:
            safe_session = session_filter.replace("'", "''")
            filters.append(f"session_id eq '{safe_session}'")
        odata_filter = " and ".join(filters) if filters else None

        vector_query = VectorizedQuery(
            vector=query_vector,
            k_nearest_neighbors=top_k * 2,  # Over-fetch before RRF merge
            fields="content_vector",
        )

        client = self._get_search_client(index_name)
        try:
            search_kwargs: dict[str, Any] = {
                "search_text": query_text,
                "vector_queries": [vector_query],
                "select": ["id", "content", "source_id", "drug_name",
                           "chunk_index", "pillar", "extra_metadata", "ingested_at"],
                "top": top_k,
                "filter": odata_filter,
            }
            if use_semantic_ranker:
                search_kwargs["query_type"] = "semantic"
                search_kwargs["semantic_configuration_name"] = SEMANTIC_CONFIG_NAME
                search_kwargs["query_caption"] = "extractive"
                search_kwargs["query_answer"] = "extractive"

            results = []
            async for result in await client.search(**search_kwargs):
                results.append({
                    "content": result.get("content", ""),
                    "score": result.get("@search.score", 0.0),
                    "reranker_score": result.get("@search.reranker_score"),
                    "source_id": result.get("source_id", ""),
                    "drug_name": result.get("drug_name", ""),
                    "chunk_index": result.get("chunk_index", 0),
                    "pillar": result.get("pillar", pillar),
                    "extra_metadata": result.get("extra_metadata", ""),
                    "ingested_at": result.get("ingested_at", ""),
                })
            return results

        except (HttpResponseError, ServiceRequestError) as e:
            logger.error(
                "AI Search hybrid query failed",
                extra={"index": index_name, "error": str(e)},
            )
            return []

    async def multi_pillar_search(
        self,
        query_text: str,
        query_vector: list[float],
        pillars: list[str],
        top_k_per_pillar: int = 3,
        drug_name_filter: str = "",
    ) -> list[dict[str, Any]]:
        """
        Search across multiple pillar indexes concurrently and merge by score.

        Uses asyncio.gather — all pillar searches run in parallel.
        Results de-duplicated by source_id+chunk_index and sorted by reranker_score.
        """
        import asyncio

        searches = [
            self.hybrid_search(
                query_text=query_text,
                query_vector=query_vector,
                pillar=pillar,
                top_k=top_k_per_pillar,
                drug_name_filter=drug_name_filter,
            )
            for pillar in pillars
        ]
        all_results_lists = await asyncio.gather(*searches)

        # Flatten and deduplicate by unique doc key
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for results in all_results_lists:
            for r in results:
                key = f"{r['source_id']}::{r['chunk_index']}"
                if key not in seen:
                    seen.add(key)
                    merged.append(r)

        # Sort by reranker_score if available, else search score
        merged.sort(
            key=lambda x: x.get("reranker_score") or x.get("score", 0),
            reverse=True,
        )
        return merged

    async def delete_by_source(self, source_id: str, pillar: str) -> int:
        """
        Delete all chunks for a given source document.
        Used to re-ingest an updated document cleanly.
        """
        index_name = PILLAR_INDEXES.get(pillar.upper())
        if not index_name:
            return 0

        client = self._get_search_client(index_name)
        try:
            # Search for all chunks of this source
            results = []
            async for r in await client.search(
                search_text="*",
                filter=f"source_id eq '{source_id}'",
                select=["id"],
                top=1000,
            ):
                results.append({"id": r["id"]})

            if results:
                await client.delete_documents(documents=results)
                logger.info(
                    "Deleted source chunks",
                    extra={"source_id": source_id, "count": len(results)},
                )
            return len(results)
        except Exception as e:
            logger.error("Delete by source failed", extra={"error": str(e)})
            return 0

    async def close(self) -> None:
        """Close all open async search clients."""
        for client in self._search_clients.values():
            await client.close()
        self._search_clients.clear()


# ── Module-level singleton ────────────────────────────────
_client: AISearchRAGClient | None = None


def get_ai_search_client() -> AISearchRAGClient:
    """Return shared singleton AISearchRAGClient."""
    global _client
    if _client is None:
        _client = AISearchRAGClient()
    return _client
