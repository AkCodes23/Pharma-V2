"""
Pharma Agentic AI — Clinical Retriever: Deterministic API Tools.

Pure-function API clients for clinical trial data retrieval.
Uses ClinicalTrials.gov v2 API (real) and CDSCO (mock).
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
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPError),
)
def search_clinical_trials(
    condition: str | None = None,
    intervention: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    country: str | None = None,
    max_results: int = 20,
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search ClinicalTrials.gov v2 API for active trials.

    Uses the official CTGOV v2 REST API.

    Args:
        condition: Disease/condition to search.
        intervention: Drug/intervention name.
        phase: Trial phase filter (e.g., "PHASE3").
        status: Recruitment status filter.
        country: Country filter.
        max_results: Maximum results to return.

    Returns:
        Tuple of (trial_records, citation).
    """
    base_url = "https://clinicaltrials.gov/api/v2/studies"

    query_parts = []
    if condition:
        query_parts.append(f"COND={condition}")
    if intervention:
        query_parts.append(f"INTR={intervention}")

    params: dict[str, Any] = {
        "pageSize": min(max_results, 50),
        "format": "json",
    }
    if query_parts:
        params["query.cond"] = condition or ""
        params["query.intr"] = intervention or ""
    if phase:
        params["filter.advanced"] = f"AREA[Phase]{phase}"
    if status:
        params["filter.overallStatus"] = status

    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        response = client.get(base_url, params=params)
        response.raise_for_status()

    raw_text = response.text
    data = response.json()

    trials = []
    for study in data.get("studies", []):
        protocol = study.get("protocolSection", {})
        id_module = protocol.get("identificationModule", {})
        status_module = protocol.get("statusModule", {})
        design_module = protocol.get("designModule", {})
        contacts = protocol.get("contactsLocationsModule", {})

        trials.append({
            "nct_id": id_module.get("nctId", ""),
            "title": id_module.get("briefTitle", ""),
            "overall_status": status_module.get("overallStatus", ""),
            "start_date": status_module.get("startDateStruct", {}).get("date", ""),
            "completion_date": status_module.get("completionDateStruct", {}).get("date", ""),
            "phase": design_module.get("phases", []),
            "enrollment": design_module.get("enrollmentInfo", {}).get("count", 0),
            "study_type": design_module.get("studyType", ""),
            "locations": [
                loc.get("country", "")
                for loc in contacts.get("locations", [])
            ][:5],  # Cap at 5 locations for brevity
        })

    citation = Citation(
        source_name="ClinicalTrials.gov v2 API",
        source_url=str(response.url),
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash_response(raw_text),
        excerpt=f"Found {len(trials)} trials for intervention={intervention}, condition={condition}",
    )

    logger.info(
        "ClinicalTrials.gov search completed",
        extra={"intervention": intervention, "trial_count": len(trials)},
    )

    return trials, citation


def search_cdsco(
    drug_name: str,
    market: str = "India",
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search CDSCO database for India-specific trial/approval data.

    NOTE: CDSCO does not have a public REST API. This is a mock
    for MVP. In production, replace with a licensed data feed or
    scraping service.

    Args:
        drug_name: Drug name to search.
        market: Target market (default: India).

    Returns:
        Tuple of (approval_records, citation).
    """
    mock_data = [
        {
            "drug_name": drug_name,
            "application_type": "New Drug Application",
            "status": "Under Review",
            "manufacturer": "Generic Pharma Ltd.",
            "submission_date": "2025-06-15",
            "market": market,
            "therapeutic_category": "Oncology",
        },
    ]

    mock_json = json.dumps(mock_data)
    citation = Citation(
        source_name="CDSCO Drug Database",
        source_url=f"https://cdsco.gov.in/drugs/search?q={drug_name}",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash_response(mock_json),
        excerpt=f"[MOCK] Found {len(mock_data)} CDSCO records for {drug_name} in {market}",
    )

    return mock_data, citation
