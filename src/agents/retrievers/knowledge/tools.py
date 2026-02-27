"""
Pharma Agentic AI — Knowledge Retriever: Azure AI Search Tools.

Internal RAG agent for hybrid search over company documents.
Uses Azure AI Search with semantic + keyword ranking.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from src.shared.config import get_settings
from src.shared.models.schemas import Citation

logger = logging.getLogger(__name__)


def _hash(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def hybrid_search(
    query: str,
    top_k: int = 5,
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Execute a hybrid search (keyword + semantic) against Azure AI Search.

    Mock for MVP. In production, uses Azure AI Search SDK with
    Semantic Ranker enabled.

    Args:
        query: Natural-language search query.
        top_k: Number of top results to return.

    Returns:
        Tuple of (search_results, citation).
    """
    # Mock implementation
    mock_results = [
        {
            "document_id": "doc-001",
            "title": "Internal Market Analysis - Oncology Portfolio",
            "content_snippet": "The oncology portfolio represents 45% of total pipeline value...",
            "relevance_score": 0.92,
            "source": "SharePoint/Strategy/",
            "last_modified": "2025-11-15",
        },
        {
            "document_id": "doc-002",
            "title": "Competitive Intelligence Brief - Biosimilar Landscape",
            "content_snippet": "Three biosimilar manufacturers have filed for approval...",
            "relevance_score": 0.87,
            "source": "SharePoint/Competitive Intel/",
            "last_modified": "2025-12-01",
        },
    ]

    raw = json.dumps(mock_results)
    citation = Citation(
        source_name="Azure AI Search (Internal Documents)",
        source_url=f"https://search.example.com/indexes/pharma-internal-docs/docs/search?q={query}",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash(raw),
        excerpt=f"[MOCK] Found {len(mock_results)} internal documents for query: {query[:50]}...",
    )

    return mock_results, citation
