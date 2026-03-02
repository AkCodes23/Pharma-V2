"""
Pharma Agentic AI — Social/Regulatory Retriever: FDA FAERS + PubMed Tools.

Deterministic API clients for adverse event and safety signal data.
Uses the real openFDA FAERS API and NCBI PubMed E-utilities for
comprehensive social/regulatory intelligence.

Architecture context:
  - Service: Social Retriever Agent
  - Responsibility: Adverse event monitoring + literature sentiment
  - Data sources: FDA FAERS (openFDA), PubMed (NCBI E-utilities)
  - Failure: Circuit breaker per API; partial results returned on failure
"""

from __future__ import annotations

import atexit
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.shared.models.schemas import Citation

logger = logging.getLogger(__name__)
_HTTP_TIMEOUT = 30.0
_HTTP_CLIENT: httpx.Client | None = None


def _hash(data: str | bytes) -> str:
    """Compute SHA-256 hash for citation integrity."""
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def _get_http_client() -> httpx.Client:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        _HTTP_CLIENT = httpx.Client(
            timeout=_HTTP_TIMEOUT,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _HTTP_CLIENT


def _close_client() -> None:
    if _HTTP_CLIENT is not None:
        _HTTP_CLIENT.close()


atexit.register(_close_client)


# ── FDA FAERS (openFDA API) ────────────────────────────────


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

    client = _get_http_client()
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


# ── PubMed (NCBI E-utilities) ──────────────────────────────


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPError),
)
def search_pubmed_safety(
    drug_name: str,
    max_results: int = 10,
) -> tuple[list[dict[str, Any]], Citation]:
    """
    Search PubMed for recent drug safety discussion papers.

    Uses the NCBI E-utilities API (free, public, no key required)
    to find safety/adverse event literature.

    Args:
        drug_name: Drug name to search.
        max_results: Maximum articles to return.

    Returns:
        Tuple of (article_records, citation).
    """
    # Step 1: Search for PMIDs
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    search_params = {
        "db": "pubmed",
        "term": f'("{drug_name}"[Title/Abstract]) AND ("safety"[Title/Abstract] OR "adverse"[Title/Abstract])',
        "retmax": min(max_results, 50),
        "sort": "date",
        "retmode": "json",
    }

    client = _get_http_client()
    search_resp = client.get(search_url, params=search_params)
    search_resp.raise_for_status()

    search_data = search_resp.json()
    pmids = search_data.get("esearchresult", {}).get("idlist", [])

    if not pmids:
        logger.info("No PubMed safety articles found", extra={"drug_name": drug_name})
        return _empty_pubmed_result(drug_name)

    # Step 2: Fetch article summaries
    summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    summary_params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "json",
    }

    summary_resp = client.get(summary_url, params=summary_params)
    summary_resp.raise_for_status()

    raw_text = summary_resp.text
    summary_data = summary_resp.json()
    result_map = summary_data.get("result", {})

    articles = []
    for pmid in pmids:
        article = result_map.get(pmid, {})
        if not article or pmid == "uids":
            continue

        # Extract authors
        author_list = article.get("authors", [])
        first_author = author_list[0].get("name", "") if author_list else ""

        articles.append({
            "pmid": pmid,
            "title": article.get("title", ""),
            "first_author": first_author,
            "journal": article.get("source", ""),
            "pub_date": article.get("pubdate", ""),
            "pub_type": article.get("pubtype", []),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })

    citation = Citation(
        source_name="PubMed (NCBI E-utilities)",
        source_url=f"https://pubmed.ncbi.nlm.nih.gov/?term={quote(drug_name)}+safety",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash(raw_text),
        excerpt=f"Found {len(articles)} safety-related publications for {drug_name}",
    )

    logger.info(
        "PubMed safety search completed",
        extra={"drug_name": drug_name, "article_count": len(articles)},
    )

    return articles, citation


def aggregate_sentiment(
    safety_score: dict[str, Any],
    pubmed_articles: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Aggregate FAERS safety data and PubMed literature into an
    overall social/regulatory sentiment signal.

    Combines adverse event severity with publication volume and
    recency to produce a composite risk assessment.

    This is a deterministic computation — no LLM involvement.

    Args:
        safety_score: Output from compute_safety_score().
        pubmed_articles: Output from search_pubmed_safety().

    Returns:
        Composite sentiment assessment dict.
    """
    faers_risk = safety_score.get("risk_level", "LOW")
    faers_events = safety_score.get("total_events", 0)
    serious_pct = safety_score.get("serious_pct", 0.0)

    # Literature volume signal: more safety papers = more scrutiny
    literature_count = len(pubmed_articles)
    if literature_count >= 20:
        literature_signal = "HIGH_SCRUTINY"
    elif literature_count >= 10:
        literature_signal = "MODERATE_SCRUTINY"
    elif literature_count >= 3:
        literature_signal = "NORMAL"
    else:
        literature_signal = "LIMITED_DATA"

    # Composite risk mapping
    risk_matrix = {
        ("CRITICAL", "HIGH_SCRUTINY"): "CRITICAL",
        ("CRITICAL", "MODERATE_SCRUTINY"): "CRITICAL",
        ("HIGH", "HIGH_SCRUTINY"): "HIGH",
        ("HIGH", "MODERATE_SCRUTINY"): "HIGH",
        ("MEDIUM", "HIGH_SCRUTINY"): "HIGH",
    }

    composite_risk = risk_matrix.get(
        (faers_risk, literature_signal),
        faers_risk,  # fallback to FAERS risk level
    )

    return {
        "composite_risk_level": composite_risk,
        "faers_risk_level": faers_risk,
        "faers_total_events": faers_events,
        "faers_serious_pct": serious_pct,
        "literature_signal": literature_signal,
        "literature_count": literature_count,
        "recommendation": _risk_recommendation(composite_risk),
        "data_sources": ["FDA FAERS", "PubMed"],
    }


def _risk_recommendation(risk_level: str) -> str:
    """Map risk level to actionable recommendation."""
    recommendations = {
        "CRITICAL": "Significant safety concerns — regulatory review required before market entry",
        "HIGH": "Elevated safety signals — REMS/RMP may be required, monitor closely",
        "MEDIUM": "Moderate safety profile — standard pharmacovigilance sufficient",
        "LOW": "Favorable safety profile — no significant safety barriers",
    }
    return recommendations.get(risk_level, "Insufficient data for risk assessment")


def _empty_pubmed_result(drug_name: str) -> tuple[list[dict[str, Any]], Citation]:
    """Return empty PubMed results with citation."""
    citation = Citation(
        source_name="PubMed (NCBI E-utilities)",
        source_url=f"https://pubmed.ncbi.nlm.nih.gov/?term={quote(drug_name)}+safety",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash("empty"),
        excerpt=f"No safety-related publications found for {drug_name}",
    )
    return [], citation
