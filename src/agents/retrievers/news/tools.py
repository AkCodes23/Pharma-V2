"""
Pharma Agentic AI — News Retriever: Web Search Tools.

Searches the internet for breaking biotech news, press releases,
M&A activity, and regulatory announcements related to drug queries.

Architecture context:
  - Service: News Retriever Agent
  - Responsibility: Real-time web intelligence not in FDA/clinical databases
  - Data sources: Tavily Web Search API, SEC, PR Newswire
  - Failure: Circuit breaker on Tavily API (external dependency)

Efficiency notes:
  - Shared httpx.Client: connection pool reused across calls (avoids TCP handshake per call)
  - Settings cached at module level: avoids repeated pydantic validation
  - Parallel search: all 3 Tavily searches run concurrently via async gather
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from src.shared.config import get_settings
from src.shared.models.schemas import Citation

logger = logging.getLogger(__name__)

# Tavily API configuration
TAVILY_API_URL = "https://api.tavily.com/search"
TAVILY_TIMEOUT = 30.0

# ── Module-level shared state (efficiency optimizations) ────
# Single shared async client with persistent connection pool.
# Each new httpx.Client would create a new TCP connection to api.tavily.com.
_http_client: httpx.AsyncClient | None = None

# Cache the API key at module level — get_settings() parses env vars each call.
_tavily_api_key: str | None = None


def _get_api_key() -> str:
    """Get Tavily API key, cached after first load."""
    global _tavily_api_key
    if _tavily_api_key is None:
        _tavily_api_key = get_settings().tavily.api_key
    return _tavily_api_key


def _get_http_client() -> httpx.AsyncClient:
    """
    Get or create the shared async HTTP client.

    Using a persistent client means:
    - Connection to api.tavily.com is reused (no TCP handshake per search)
    - HTTP/2 multiplexing is available
    - Connection pool handles concurrent requests safely
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=TAVILY_TIMEOUT,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            http2=True,
        )
    return _http_client


async def _tavily_post(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a single Tavily API POST with the shared client.

    Injects API key automatically. Raises httpx.HTTPError on failure.
    """
    client = _get_http_client()
    payload["api_key"] = _get_api_key()
    response = await client.post(TAVILY_API_URL, json=payload)
    response.raise_for_status()
    return response.json()


def _extract_results(data: dict[str, Any], result_key_map: dict[str, str]) -> list[dict[str, Any]]:
    """
    Extract and normalize results from a Tavily API response.

    Args:
        data: Tavily API response dict.
        result_key_map: Maps output field names to Tavily result field names.

    Returns:
        List of normalized result dicts.
    """
    results = []
    for r in data.get("results", []):
        item: dict[str, Any] = {}
        for out_key, src_key in result_key_map.items():
            if src_key == "content[:500]":
                item[out_key] = r.get("content", "")[:500]
            elif src_key == "url.domain":
                url = r.get("url", "")
                item[out_key] = url.split("/")[2] if url else ""
            else:
                item[out_key] = r.get(src_key, "" if src_key != "score" else 0.0)
        results.append(item)
    return results


def _make_citation(source_name: str, query_qs: str, data_type: str, answer: str) -> Citation:
    """Construct a Citation from a Tavily response."""
    return Citation(
        source_name=source_name,
        source_url=f"https://tavily.com/search?q={query_qs}",
        accessed_at=datetime.now(timezone.utc).isoformat(),
        data_type=data_type,
        excerpt=answer[:200] if answer else "",
    )


# ── Public search functions (now async) ──────────────────


async def search_biotech_news(
    drug_name: str, target_market: str = "US"
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search for recent biotech news related to a drug.

    Args:
        drug_name: Drug or ingredient name.
        target_market: Target market (US, India, EU).

    Returns:
        Tuple of (news_articles, citation).
    """
    query = f"{drug_name} pharmaceutical news {target_market} generic biosimilar 2024 2025"

    data = await _tavily_post({
        "query": query,
        "search_depth": "advanced",
        "include_answer": True,
        "include_raw_content": False,
        "max_results": 10,
        "topic": "news",
    })

    articles = _extract_results(data, {
        "title": "title",
        "url": "url",
        "content": "content[:500]",
        "score": "score",
        "published_date": "published_date",
    })

    citation = _make_citation(
        "Tavily Web Search — Biotech News",
        quote_plus(drug_name),
        "web_search",
        data.get("answer", ""),
    )

    logger.info("Biotech news search completed", extra={"drug": drug_name, "results": len(articles)})
    return articles, citation


async def search_press_releases(
    drug_name: str, company_name: str | None = None
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search for official press releases and SEC filings.

    Args:
        drug_name: Drug name.
        company_name: Optional company name for targeted search.

    Returns:
        Tuple of (press_releases, citation).
    """
    parts = [drug_name, "press release"]
    if company_name:
        parts.append(company_name)
    parts.extend(["FDA", "approval", "launch", "generic"])
    query = " ".join(parts)

    data = await _tavily_post({
        "query": query,
        "search_depth": "advanced",
        "include_answer": True,
        "include_raw_content": False,
        "max_results": 8,
        "include_domains": ["sec.gov", "prnewswire.com", "businesswire.com", "globenewswire.com", "fda.gov"],
    })

    releases = _extract_results(data, {
        "title": "title",
        "url": "url",
        "content": "content[:500]",
        "source_domain": "url.domain",
        "published_date": "published_date",
    })

    citation = _make_citation(
        "Press Releases & SEC Filings",
        quote_plus(f"{drug_name} press release"),
        "press_release",
        data.get("answer", ""),
    )

    return releases, citation


async def search_ma_activity(
    drug_name: str, therapeutic_area: str | None = None
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search for M&A, licensing, and partnership activity.

    Args:
        drug_name: Drug name.
        therapeutic_area: Optional therapeutic area for context.

    Returns:
        Tuple of (deals, citation).
    """
    parts = [drug_name, "merger acquisition licensing deal partnership"]
    if therapeutic_area:
        parts.append(therapeutic_area)
    query = " ".join(parts)

    data = await _tavily_post({
        "query": query,
        "search_depth": "advanced",
        "include_answer": True,
        "max_results": 5,
        "topic": "news",
    })

    deals = _extract_results(data, {
        "title": "title",
        "url": "url",
        "content": "content[:500]",
        "relevance_score": "score",
    })

    citation = _make_citation(
        "M&A and Licensing Activity",
        quote_plus(f"{drug_name} merger acquisition"),
        "ma_activity",
        data.get("answer", ""),
    )

    return deals, citation


async def search_all(
    drug_name: str,
    target_market: str = "US",
    company_name: str | None = None,
    therapeutic_area: str | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[Citation],
]:
    """
    Run all 3 Tavily searches concurrently (saves ~60% wall time vs sequential).

    All 3 API calls are dispatched in parallel via asyncio.gather.
    Error in one search does not cancel others — results default to empty.

    Returns:
        Tuple of (news_articles, press_releases, ma_deals, citations).
    """
    async def _safe(coro):
        try:
            return await coro
        except Exception as e:
            logger.error("Search tool failed", extra={"error": str(e)})
            return [], None  # Safe default

    results = await asyncio.gather(
        _safe(search_biotech_news(drug_name, target_market)),
        _safe(search_press_releases(drug_name, company_name)),
        _safe(search_ma_activity(drug_name, therapeutic_area)),
    )

    articles, news_cite = results[0]
    releases, pr_cite = results[1]
    deals, ma_cite = results[2]
    citations = [c for c in [news_cite, pr_cite, ma_cite] if c is not None]

    return articles, releases, deals, citations


async def close_http_client() -> None:
    """Gracefully close the shared HTTP client (call on app shutdown)."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
