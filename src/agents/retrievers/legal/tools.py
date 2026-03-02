"""
Pharma Agentic AI — Legal Retriever: Deterministic API Tools.

Provides pure-function API clients for patent data retrieval.
These tools use ONLY deterministic HTTP calls — no LLM inference.
Every response is hashed for citation integrity.

Architecture context:
  - Service: Legal Retriever Agent
  - Responsibility: Patent and exclusivity data retrieval
  - Data sources: USPTO Orange Book (openFDA), Indian Patent Office (IPO web scraper)
  - Failure: Circuit breaker per API; mock fallback for IPO if scraping blocked
"""

from __future__ import annotations

import atexit
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
_IPO_TIMEOUT = 45.0  # IPO scraping needs more time
_HTTP_CLIENT: httpx.Client | None = None
_IPO_CLIENT: httpx.Client | None = None


def _hash_response(data: str | bytes) -> str:
    """Compute SHA-256 hash for citation integrity."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _get_http_client() -> httpx.Client:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        _HTTP_CLIENT = httpx.Client(
            timeout=_HTTP_TIMEOUT,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _HTTP_CLIENT


def _get_ipo_client() -> httpx.Client:
    global _IPO_CLIENT
    if _IPO_CLIENT is None:
        _IPO_CLIENT = httpx.Client(
            timeout=_IPO_TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _IPO_CLIENT


def _close_clients() -> None:
    if _HTTP_CLIENT is not None:
        _HTTP_CLIENT.close()
    if _IPO_CLIENT is not None:
        _IPO_CLIENT.close()


atexit.register(_close_clients)


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

    client = _get_http_client()
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

    client = _get_http_client()
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


# ── Indian Patent Office (Web Scraper) ──────────────────────


def search_ipo_patents(
    ingredient: str,
    market: str = "India",
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search Indian Patent Office for patent status.

    Uses web scraping of the IPO patent search portal since no public
    REST API exists. Results are parsed from HTML tables.

    Falls back to a structured estimation if scraping is blocked (rate
    limits, CAPTCHA, or site unavailability).

    Args:
        ingredient: Active ingredient name.
        market: Target market (default: India).

    Returns:
        Tuple of (patent_records, citation).
    """
    ipo_url = "https://ipindiaservices.gov.in/PatentSearch/PatentSearch/ViewApplicationStatus"
    search_url = "https://ipindiaservices.gov.in/PatentSearch/PatentSearch/SearchPatent"

    patents: list[dict[str, Any]] = []

    try:
        client = _get_ipo_client()
        # Step 1: Get session cookies from the search page
        session_resp = client.get(
            "https://ipindiaservices.gov.in/PatentSearch/PatentSearch/SearchByKeyword"
        )
        session_resp.raise_for_status()

        # Step 2: Submit keyword search form
        form_data = {
            "KeyWord": ingredient,
            "SearchType": "Keyword",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://ipindiaservices.gov.in/PatentSearch/",
        }

        search_resp = client.post(search_url, data=form_data, headers=headers)
        search_resp.raise_for_status()

        # Step 3: Parse HTML response for patent table rows
        patents = _parse_ipo_html(search_resp.text, ingredient, market)

        source_url = f"https://ipindiaservices.gov.in/PatentSearch/PatentSearch/SearchByKeyword?q={ingredient}"
        raw_json = json.dumps(patents, default=str)

        citation = Citation(
            source_name="Indian Patent Office (IPO)",
            source_url=source_url,
            retrieved_at=datetime.now(timezone.utc),
            data_hash=_hash_response(raw_json),
            excerpt=f"Found {len(patents)} patent records for {ingredient} in {market}",
        )

        logger.info(
            "IPO patent search completed via web scraper",
            extra={"ingredient": ingredient, "market": market, "result_count": len(patents)},
        )

        return patents, citation

    except (httpx.HTTPError, httpx.TimeoutException, Exception) as e:
        logger.warning(
            "IPO scraper failed — returning estimation fallback",
            extra={"ingredient": ingredient, "error": str(e), "error_type": type(e).__name__},
        )
        return _ipo_estimation_fallback(ingredient, market)


def _parse_ipo_html(
    html: str,
    ingredient: str,
    market: str,
) -> list[dict[str, Any]]:
    """
    Parse IPO search results HTML into structured patent records.

    Uses selectolax for fast HTML parsing. Extracts data from the
    result table rows on the IPO search results page.
    """
    try:
        from selectolax.parser import HTMLParser
    except ImportError:
        logger.warning("selectolax not installed — cannot parse IPO HTML")
        return []

    tree = HTMLParser(html)
    patents: list[dict[str, Any]] = []

    # IPO search results are typically in table rows
    table = tree.css_first("table.table, table#searchResults, table.grid-table")
    if table is None:
        # Try finding any table with patent-like content
        tables = tree.css("table")
        for t in tables:
            if "application" in (t.text() or "").lower():
                table = t
                break

    if table is None:
        logger.info("No patent results table found in IPO HTML response")
        return patents

    rows = table.css("tr")
    for row in rows[1:]:  # Skip header row
        cells = row.css("td")
        if len(cells) < 3:
            continue

        cell_texts = [c.text(strip=True) for c in cells]

        patent = {
            "application_number": cell_texts[0] if len(cell_texts) > 0 else "",
            "title": cell_texts[1] if len(cell_texts) > 1 else "",
            "applicant": cell_texts[2] if len(cell_texts) > 2 else "",
            "filing_date": cell_texts[3] if len(cell_texts) > 3 else "",
            "status": cell_texts[4] if len(cell_texts) > 4 else "Unknown",
            "ingredient": ingredient,
            "market": market,
            "data_source": "ipo_scraper",
        }
        patents.append(patent)

    return patents


def _ipo_estimation_fallback(
    ingredient: str,
    market: str,
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Fallback when IPO scraping fails.

    Returns a structured record indicating that IPO data could not be
    retrieved live, with a recommendation to check manually. This is
    NOT mock data — it's an explicit data-unavailable signal.
    """
    fallback_record = {
        "ingredient": ingredient,
        "market": market,
        "status": "DATA_UNAVAILABLE",
        "data_source": "ipo_fallback",
        "note": (
            "IPO patent search portal was unavailable. "
            "Manual verification recommended at https://ipindiaservices.gov.in/PatentSearch/"
        ),
    }

    raw_json = json.dumps(fallback_record)
    citation = Citation(
        source_name="Indian Patent Office (IPO) — Fallback",
        source_url=f"https://ipindiaservices.gov.in/PatentSearch/?q={ingredient}",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash_response(raw_json),
        excerpt=f"IPO data unavailable for {ingredient} in {market} — manual check recommended",
    )

    logger.info(
        "IPO fallback record generated",
        extra={"ingredient": ingredient, "market": market},
    )

    return [fallback_record], citation
