"""
Pharma Agentic AI — Clinical Retriever: Deterministic API Tools.

Provides API clients for clinical trial data retrieval.
Uses ClinicalTrials.gov v2 API (real) and CDSCO web scraper.

Architecture context:
  - Service: Clinical Retriever Agent
  - Responsibility: Clinical trial landscape analysis
  - Data sources: ClinicalTrials.gov v2 API, CDSCO (web scraper)
  - Failure: Circuit breaker per API; explicit DATA_UNAVAILABLE for CDSCO
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.shared.models.schemas import Citation

logger = logging.getLogger(__name__)
_HTTP_TIMEOUT = 30.0
_CDSCO_TIMEOUT = 45.0


def _hash_response(data: str | bytes) -> str:
    """Compute SHA-256 hash for citation integrity."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ── ClinicalTrials.gov v2 API ──────────────────────────────


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPError),
)
def search_clinical_trials(
    drug_name: str,
    status: str = "RECRUITING",
    max_results: int = 10,
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search ClinicalTrials.gov for active/completed trials.

    Uses the ClinicalTrials.gov v2 API with structured query format.

    Args:
        drug_name: Drug or ingredient name.
        status: Trial status filter (RECRUITING, COMPLETED, etc.).
        max_results: Maximum trials to return.

    Returns:
        Tuple of (trial_records, citation).
    """
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.term": drug_name,
        "filter.overallStatus": status,
        "pageSize": min(max_results, 50),
        "format": "json",
        "fields": (
            "NCTId,BriefTitle,OverallStatus,Phase,StartDate,"
            "CompletionDate,EnrollmentCount,LeadSponsorName,"
            "Condition,InterventionName"
        ),
    }

    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        response = client.get(base_url, params=params)
        response.raise_for_status()

    raw_text = response.text
    data = response.json()
    studies = data.get("studies", [])

    trials = []
    for study in studies:
        protocol = study.get("protocolSection", {})
        id_module = protocol.get("identificationModule", {})
        status_module = protocol.get("statusModule", {})
        design_module = protocol.get("designModule", {})
        sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
        conditions_module = protocol.get("conditionsModule", {})
        interventions_module = protocol.get("armsInterventionsModule", {})

        trials.append({
            "nct_id": id_module.get("nctId", ""),
            "title": id_module.get("briefTitle", ""),
            "status": status_module.get("overallStatus", ""),
            "phase": ",".join(design_module.get("phases", [])),
            "start_date": status_module.get("startDateStruct", {}).get("date", ""),
            "completion_date": status_module.get("completionDateStruct", {}).get("date", ""),
            "enrollment": design_module.get("enrollmentInfo", {}).get("count", 0),
            "sponsor": sponsor_module.get("leadSponsor", {}).get("name", ""),
            "conditions": conditions_module.get("conditions", []),
            "interventions": [
                i.get("name", "")
                for i in interventions_module.get("interventions", [])
            ],
        })

    citation = Citation(
        source_name="ClinicalTrials.gov (v2 API)",
        source_url=f"https://clinicaltrials.gov/search?term={quote(drug_name)}&status={status}",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash_response(raw_text),
        excerpt=f"Found {len(trials)} {status.lower()} trials for {drug_name}",
    )

    logger.info(
        "ClinicalTrials.gov search completed",
        extra={"drug_name": drug_name, "status": status, "trial_count": len(trials)},
    )

    return trials, citation


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPError),
)
def search_fda_approvals(
    drug_name: str,
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Check FDA approval status for a drug via openFDA.

    Args:
        drug_name: Drug name to check.

    Returns:
        Tuple of (approval_records, citation).
    """
    base_url = "https://api.fda.gov/drug/drugsfda.json"
    params = {
        "search": f'openfda.generic_name:"{drug_name}"+OR+openfda.brand_name:"{drug_name}"',
        "limit": 5,
    }

    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        response = client.get(base_url, params=params)
        response.raise_for_status()

    raw_text = response.text
    data = response.json()

    approvals = []
    for result in data.get("results", []):
        for submission in result.get("submissions", []):
            if submission.get("submission_type") == "ORIG":
                approvals.append({
                    "application_number": result.get("application_number", ""),
                    "sponsor_name": result.get("sponsor_name", ""),
                    "submission_status": submission.get("submission_status", ""),
                    "submission_status_date": submission.get("submission_status_date", ""),
                    "review_priority": submission.get("review_priority", ""),
                })

    citation = Citation(
        source_name="FDA Drug Approvals (openFDA API)",
        source_url=str(response.url),
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash_response(raw_text),
        excerpt=f"Found {len(approvals)} FDA approval records for {drug_name}",
    )

    return approvals, citation


# ── CDSCO (India) — Web Scraper ─────────────────────────────


def search_cdsco_drugs(
    drug_name: str,
    market: str = "India",
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search CDSCO for drug approval and regulatory status in India.

    CDSCO does not have a public REST API. This function scrapes
    the CDSCO online portal for drug registration data.

    Falls back to an explicit DATA_UNAVAILABLE record when scraping
    fails (rate limits, CAPTCHA, site changes).

    Args:
        drug_name: Drug name to search.
        market: Target market (default: India).

    Returns:
        Tuple of (drug_records, citation).
    """
    cdsco_search_url = "https://cdscoonline.gov.in/CDSCO/Drugs"

    try:
        with httpx.Client(timeout=_CDSCO_TIMEOUT, follow_redirects=True) as client:
            # Step 1: Get the main search page for session/cookies
            page_resp = client.get("https://cdscoonline.gov.in/CDSCO/Drugs")
            page_resp.raise_for_status()

            # Step 2: Submit search form
            form_data = {
                "DrugName": drug_name,
                "SearchType": "DrugName",
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://cdscoonline.gov.in/CDSCO/Drugs",
            }

            search_resp = client.post(cdsco_search_url, data=form_data, headers=headers)
            search_resp.raise_for_status()

            # Step 3: Parse HTML results
            records = _parse_cdsco_html(search_resp.text, drug_name, market)

        raw_json = json.dumps(records, default=str)
        citation = Citation(
            source_name="CDSCO (Central Drugs Standard Control Organisation)",
            source_url=f"https://cdscoonline.gov.in/CDSCO/Drugs?q={quote(drug_name)}",
            retrieved_at=datetime.now(timezone.utc),
            data_hash=_hash_response(raw_json),
            excerpt=f"Found {len(records)} CDSCO records for {drug_name} in {market}",
        )

        logger.info(
            "CDSCO search completed via web scraper",
            extra={"drug_name": drug_name, "market": market, "record_count": len(records)},
        )

        return records, citation

    except (httpx.HTTPError, httpx.TimeoutException, Exception) as e:
        logger.warning(
            "CDSCO scraper failed — returning unavailable fallback",
            extra={"drug_name": drug_name, "error": str(e), "error_type": type(e).__name__},
        )
        return _cdsco_fallback(drug_name, market)


def _parse_cdsco_html(
    html: str,
    drug_name: str,
    market: str,
) -> list[dict[str, Any]]:
    """Parse CDSCO search results HTML into structured records."""
    try:
        from selectolax.parser import HTMLParser
    except ImportError:
        logger.warning("selectolax not installed — cannot parse CDSCO HTML")
        return []

    tree = HTMLParser(html)
    records: list[dict[str, Any]] = []

    # CDSCO results are typically in table format
    table = tree.css_first("table.table, table#drugResults, table.grid-table")
    if table is None:
        tables = tree.css("table")
        for t in tables:
            text = (t.text() or "").lower()
            if "drug" in text or "approval" in text:
                table = t
                break

    if table is None:
        logger.info("No drug results table found in CDSCO HTML")
        return records

    rows = table.css("tr")
    for row in rows[1:]:  # Skip header
        cells = row.css("td")
        if len(cells) < 2:
            continue

        cell_texts = [c.text(strip=True) for c in cells]

        record = {
            "drug_name": cell_texts[0] if len(cell_texts) > 0 else drug_name,
            "manufacturer": cell_texts[1] if len(cell_texts) > 1 else "",
            "approval_number": cell_texts[2] if len(cell_texts) > 2 else "",
            "approval_date": cell_texts[3] if len(cell_texts) > 3 else "",
            "status": cell_texts[4] if len(cell_texts) > 4 else "Unknown",
            "market": market,
            "data_source": "cdsco_scraper",
        }
        records.append(record)

    return records


def _cdsco_fallback(
    drug_name: str,
    market: str,
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Fallback when CDSCO scraping fails.

    Returns an explicit DATA_UNAVAILABLE record — not mock data.
    """
    fallback_record = {
        "drug_name": drug_name,
        "market": market,
        "status": "DATA_UNAVAILABLE",
        "data_source": "cdsco_fallback",
        "note": (
            "CDSCO online portal was unavailable for automated search. "
            "Manual verification recommended at https://cdscoonline.gov.in/CDSCO/Drugs"
        ),
    }

    raw_json = json.dumps(fallback_record)
    citation = Citation(
        source_name="CDSCO — Fallback",
        source_url=f"https://cdscoonline.gov.in/CDSCO/Drugs?q={quote(drug_name)}",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash_response(raw_json),
        excerpt=f"CDSCO data unavailable for {drug_name} in {market} — manual check recommended",
    )

    return [fallback_record], citation
