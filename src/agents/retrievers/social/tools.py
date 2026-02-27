"""
Pharma Agentic AI — Social/Regulatory Retriever: FDA FAERS Tools.

Deterministic API clients for adverse event and safety signal data.
Uses the real openFDA FAERS API for adverse event analysis.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.shared.models.schemas import Citation

logger = logging.getLogger(__name__)
_HTTP_TIMEOUT = 30.0


def _hash(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPError),
)
def search_faers(
    drug_name: str,
    max_results: int = 10,
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search FDA Adverse Event Reporting System (FAERS) via openFDA.

    Returns adverse event reports for the given drug.

    Args:
        drug_name: Drug name to search.
        max_results: Maximum reports to return.

    Returns:
        Tuple of (adverse_event_records, citation).
    """
    base_url = "https://api.fda.gov/drug/event.json"
    params = {
        "search": f'patient.drug.openfda.generic_name:"{drug_name}"',
        "limit": min(max_results, 100),
    }

    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        response = client.get(base_url, params=params)
        response.raise_for_status()

    raw_text = response.text
    data = response.json()

    events = []
    for result in data.get("results", []):
        events.append({
            "report_id": result.get("safetyreportid", ""),
            "receive_date": result.get("receivedate", ""),
            "serious": result.get("serious", 0),
            "seriousness_death": result.get("seriousnessdeath", 0),
            "seriousness_hospitalization": result.get("seriousnesshospitalization", 0),
            "reactions": [
                r.get("reactionmeddrapt", "")
                for r in result.get("patient", {}).get("reaction", [])
            ],
            "drug_characterization": [
                d.get("drugcharacterization", "")
                for d in result.get("patient", {}).get("drug", [])
            ][:3],
            "patient_sex": result.get("patient", {}).get("patientsex", ""),
            "patient_age": result.get("patient", {}).get("patientonsetage", ""),
            "country": result.get("occurcountry", ""),
        })

    citation = Citation(
        source_name="FDA FAERS (openFDA API)",
        source_url=str(response.url),
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash(raw_text),
        excerpt=f"Found {len(events)} adverse event reports for {drug_name}",
    )

    logger.info(
        "FAERS search completed",
        extra={"drug_name": drug_name, "event_count": len(events)},
    )

    return events, citation


def compute_safety_score(events: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute a safety risk score from adverse event data.

    Returns a risk assessment with severity breakdown.
    This is a deterministic computation — no LLM involvement.
    """
    total = len(events)
    if total == 0:
        return {"risk_level": "LOW", "total_events": 0, "serious_pct": 0.0}

    serious_count = sum(1 for e in events if e.get("serious", 0) == 1)
    death_count = sum(1 for e in events if e.get("seriousness_death", 0) == 1)
    hospitalization_count = sum(1 for e in events if e.get("seriousness_hospitalization", 0) == 1)

    serious_pct = (serious_count / total) * 100
    death_pct = (death_count / total) * 100

    if death_pct > 5 or serious_pct > 50:
        risk_level = "CRITICAL"
    elif serious_pct > 25:
        risk_level = "HIGH"
    elif serious_pct > 10:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # Common reactions
    all_reactions: list[str] = []
    for e in events:
        all_reactions.extend(e.get("reactions", []))

    reaction_counts: dict[str, int] = {}
    for r in all_reactions:
        if r:
            reaction_counts[r] = reaction_counts.get(r, 0) + 1

    top_reactions = sorted(reaction_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "risk_level": risk_level,
        "total_events": total,
        "serious_count": serious_count,
        "serious_pct": round(serious_pct, 1),
        "death_count": death_count,
        "death_pct": round(death_pct, 1),
        "hospitalization_count": hospitalization_count,
        "top_reactions": [{"reaction": r, "count": c} for r, c in top_reactions],
    }
