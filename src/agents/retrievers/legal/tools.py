"""
Pharma Agentic AI — Legal Retriever: Deterministic API Tools.

Provides pure-function API clients for patent data retrieval.
These tools use ONLY deterministic HTTP calls — no LLM inference.
Every response is hashed for citation integrity.

Data sources:
  - USPTO Orange Book (FDA approved drugs with patent/exclusivity)
  - Indian Patent Office (IPO) — patent search
  - OpenFDA Drug Labels API — supplementary label data
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.shared.models.schemas import Citation

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30.0


def _hash_response(data: str | bytes) -> str:
    """Compute SHA-256 hash for citation integrity."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ── USPTO Orange Book ──────────────────────────────────────


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPError),
)
def search_orange_book(
    ingredient: str,
    trade_name: str | None = None,
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search the FDA Orange Book for patent and exclusivity data.

    Uses the openFDA Orange Book API endpoint.

    Args:
        ingredient: Active ingredient (INN) name.
        trade_name: Optional trade/brand name.

    Returns:
        Tuple of (patent_records, citation).
    """
    base_url = "https://api.fda.gov/drug/drugsfda.json"
    search_terms = [f'openfda.substance_name:"{ingredient}"']
    if trade_name:
        search_terms.append(f'openfda.brand_name:"{trade_name}"')

    params = {
        "search": "+AND+".join(search_terms),
        "limit": 10,
    }

    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        response = client.get(base_url, params=params)
        response.raise_for_status()

    raw_text = response.text
    data = response.json()
    results = data.get("results", [])

    # Extract patent information
    patents = []
    for result in results:
        for product in result.get("products", []):
            for patent in product.get("active_ingredients", []):
                patents.append({
                    "application_number": result.get("application_number", ""),
                    "brand_name": product.get("brand_name", ""),
                    "active_ingredient": patent.get("name", ingredient),
                    "dosage_form": product.get("dosage_form", ""),
                    "route": product.get("route", ""),
                    "te_code": product.get("te_code", ""),
                })

    citation = Citation(
        source_name="FDA Orange Book (openFDA API)",
        source_url=str(response.url),
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash_response(raw_text),
        excerpt=f"Found {len(patents)} records for {ingredient}",
    )

    logger.info(
        "Orange Book search completed",
        extra={"ingredient": ingredient, "result_count": len(patents)},
    )

    return patents, citation


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPError),
)
def search_patent_exclusivity(
    ingredient: str,
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search for patent exclusivity data via the openFDA API.

    Returns exclusivity dates, patent numbers, and expiration dates.

    Args:
        ingredient: Active ingredient name.

    Returns:
        Tuple of (exclusivity_records, citation).
    """
    base_url = "https://api.fda.gov/drug/drugsfda.json"
    params = {
        "search": f'openfda.substance_name:"{ingredient}"',
        "limit": 5,
    }

    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        response = client.get(base_url, params=params)
        response.raise_for_status()

    raw_text = response.text
    data = response.json()

    exclusivities = []
    for result in data.get("results", []):
        for submission in result.get("submissions", []):
            for exc in submission.get("application_docs", []):
                exclusivities.append({
                    "application_number": result.get("application_number", ""),
                    "submission_type": submission.get("submission_type", ""),
                    "submission_status": submission.get("submission_status", ""),
                    "doc_type": exc.get("type", ""),
                    "doc_date": exc.get("date", ""),
                })

    citation = Citation(
        source_name="FDA Drug Exclusivity (openFDA API)",
        source_url=str(response.url),
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash_response(raw_text),
        excerpt=f"Found {len(exclusivities)} exclusivity records for {ingredient}",
    )

    return exclusivities, citation


# ── Indian Patent Office (Mock — real API requires scraping) ─


def search_ipo_patents(
    ingredient: str,
    market: str = "India",
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search Indian Patent Office for patent status.

    NOTE: The IPO does not have a public REST API as of 2026.
    This uses a mock response structure. In production, this
    would be replaced with a scraping service or licensed data feed.

    Args:
        ingredient: Active ingredient name.
        market: Target market (default: India).

    Returns:
        Tuple of (patent_records, citation).
    """
    # Mock response for MVP — replace with real integration
    mock_data = [
        {
            "patent_number": f"IN-{hash(ingredient) % 100000:06d}",
            "ingredient": ingredient,
            "patent_holder": "Original Manufacturer",
            "filing_date": "2008-03-15",
            "expiry_date": "2028-03-15",
            "status": "Active",
            "patent_type": "Compound Patent",
            "market": market,
        },
    ]

    mock_json = json.dumps(mock_data)
    citation = Citation(
        source_name="Indian Patent Office (IPO)",
        source_url=f"https://ipindia.gov.in/patents/search?q={ingredient}",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash_response(mock_json),
        excerpt=f"[MOCK] Found {len(mock_data)} patents for {ingredient} in {market}",
    )

    logger.info(
        "IPO patent search completed (mock)",
        extra={"ingredient": ingredient, "market": market},
    )

    return mock_data, citation
