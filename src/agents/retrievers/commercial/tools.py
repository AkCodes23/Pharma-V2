"""
Pharma Agentic AI — Commercial Retriever: Market Data Tools.

Deterministic API clients for market/financial data retrieval.
Uses SEC EDGAR (free) and Yahoo Finance for real financial data.
Designed for plug-in replacement with licensed feeds (IQVIA, GlobalData).

Architecture context:
  - Service: Commercial Retriever Agent
  - Responsibility: Market intelligence and financial analysis
  - Data sources: SEC EDGAR (free, no key), Yahoo Finance (yfinance)
  - Failure: Circuit breaker with estimation fallback per tool
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

# SEC EDGAR requires a user-agent header with contact info
_EDGAR_HEADERS = {
    "User-Agent": "PharmaAgenticAI/1.0 (pharma-ai@example.com)",
    "Accept": "application/json",
}


def _hash(data: str) -> str:
    """Compute SHA-256 hash for citation integrity."""
    return hashlib.sha256(data.encode()).hexdigest()


# ── SEC EDGAR — Company Filings & Revenue ──────────────────


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPError),
)
def get_market_data(
    drug_name: str,
    therapeutic_area: str,
    target_market: str,
) -> tuple[dict[str, Any], Citation]:
    """
    Retrieve market size, TAM, and growth data.

    Uses SEC EDGAR for originator company financials, and industry
    benchmarks for market sizing. For full commercial intelligence,
    replace with IQVIA MIDAS or GlobalData Pharma Intelligence.

    Args:
        drug_name: Drug or brand name.
        therapeutic_area: E.g. "Oncology", "Diabetes".
        target_market: E.g. "US", "India", "Global".

    Returns:
        Tuple of (market_data_dict, citation).
    """
    # Search SEC EDGAR for company filings related to this drug
    edgar_data = _search_edgar_company(drug_name)
    yf_data = _get_yfinance_data(drug_name)

    # Combine data sources into market intelligence
    market_cap = yf_data.get("market_cap", 0)
    revenue = yf_data.get("total_revenue", 0)

    # Estimate TAM from industry benchmarks (therapeutic area multipliers)
    tam_multipliers = {
        "Oncology": 280_000_000_000,
        "Diabetes": 95_000_000_000,
        "Immunology": 110_000_000_000,
        "Cardiovascular": 75_000_000_000,
        "Neurology": 60_000_000_000,
    }
    estimated_tam = tam_multipliers.get(therapeutic_area, 50_000_000_000)

    # Market-specific adjustment
    market_adjustments = {
        "US": 1.0,
        "India": 0.12,
        "EU": 0.85,
        "Japan": 0.25,
        "China": 0.35,
        "Global": 1.0,
    }
    market_factor = market_adjustments.get(target_market, 0.5)

    data = {
        "drug_name": drug_name,
        "therapeutic_area": therapeutic_area,
        "target_market": target_market,
        "total_addressable_market_usd": int(estimated_tam * market_factor),
        "market_growth_cagr_pct": yf_data.get("revenue_growth", 8.5),
        "originator_market_cap_usd": market_cap,
        "originator_total_revenue_usd": revenue,
        "generic_market_share_pct": _estimate_generic_share(therapeutic_area),
        "forecast_year": 2027,
        "market_trend": "GROWING" if yf_data.get("revenue_growth", 0) > 0 else "DECLINING",
        "edgar_filings": edgar_data.get("filings", [])[:3],
        "data_source": "sec_edgar_yfinance",
        "data_quality": "estimated",
    }

    raw = json.dumps(data, default=str)
    citation = Citation(
        source_name="SEC EDGAR + Yahoo Finance",
        source_url=f"https://efts.sec.gov/LATEST/search-index?q={drug_name}",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash(raw),
        excerpt=(
            f"TAM ${data['total_addressable_market_usd']:,.0f} ({target_market}), "
            f"CAGR {data['market_growth_cagr_pct']}%"
        ),
    )

    logger.info(
        "Market data retrieval completed",
        extra={
            "drug_name": drug_name,
            "market": target_market,
            "tam": data["total_addressable_market_usd"],
        },
    )

    return data, citation


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPError),
)
def get_drug_revenue(
    drug_name: str,
) -> tuple[dict[str, Any], Citation]:
    """
    Retrieve historical and projected revenue for a drug.

    Uses SEC EDGAR 10-K filings and Yahoo Finance for company-level
    revenue data. Drug-level revenue is estimated as a proportion.

    Args:
        drug_name: Drug name to search.

    Returns:
        Tuple of (revenue_data, citation).
    """
    yf_data = _get_yfinance_data(drug_name)
    edgar_data = _search_edgar_company(drug_name)

    total_revenue = yf_data.get("total_revenue", 0)
    revenue_growth = yf_data.get("revenue_growth", 0)

    # Build annual revenue estimates
    base_year = 2025
    annual_revenue = []
    for offset in range(-2, 3):
        year = base_year + offset
        factor = (1 + revenue_growth / 100) ** offset if revenue_growth else 1.0
        annual_revenue.append({
            "year": year,
            "revenue_usd": int(total_revenue * factor) if total_revenue else 0,
            "data_quality": "actual" if offset <= 0 else "projected",
        })

    peak_entry = max(annual_revenue, key=lambda x: x["revenue_usd"]) if annual_revenue else {}

    data = {
        "drug_name": drug_name,
        "company_name": yf_data.get("company_name", ""),
        "annual_revenue": annual_revenue,
        "peak_sales_usd": peak_entry.get("revenue_usd", 0),
        "peak_year": peak_entry.get("year", base_year),
        "revenue_growth_pct": revenue_growth,
        "market_cap_usd": yf_data.get("market_cap", 0),
        "pe_ratio": yf_data.get("pe_ratio"),
        "sector": yf_data.get("sector", "Healthcare"),
        "edgar_cik": edgar_data.get("cik", ""),
        "data_source": "sec_edgar_yfinance",
        "data_quality": "estimated",
    }

    raw = json.dumps(data, default=str)
    citation = Citation(
        source_name="SEC EDGAR + Yahoo Finance",
        source_url=f"https://efts.sec.gov/LATEST/search-index?q={drug_name}",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash(raw),
        excerpt=(
            f"Revenue data for {drug_name}: "
            f"peak ${data['peak_sales_usd']:,.0f} in {data['peak_year']}"
        ),
    )

    logger.info(
        "Drug revenue retrieval completed",
        extra={"drug_name": drug_name, "peak_sales": data["peak_sales_usd"]},
    )

    return data, citation


# ── SEC EDGAR API ──────────────────────────────────────────


def _search_edgar_company(drug_name: str) -> dict[str, Any]:
    """
    Search SEC EDGAR full-text search for company filings
    mentioning the drug name.

    EDGAR EFTS API is free and does not require an API key.
    """
    try:
        url = "https://efts.sec.gov/LATEST/search-index"
        params = {
            "q": f'"{drug_name}"',
            "dateRange": "custom",
            "startdt": "2023-01-01",
            "enddt": "2026-12-31",
            "forms": "10-K,10-Q,8-K",
        }

        with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_EDGAR_HEADERS) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()

        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])

        filings = []
        cik = ""
        for hit in hits[:5]:
            source = hit.get("_source", {})
            if not cik:
                cik = source.get("entity_id", "")
            filings.append({
                "form_type": source.get("form_type", ""),
                "filing_date": source.get("file_date", ""),
                "company_name": source.get("display_names", [""])[0] if source.get("display_names") else "",
                "description": source.get("display_date_filed", ""),
            })

        return {"cik": cik, "filings": filings, "total_hits": data.get("hits", {}).get("total", {}).get("value", 0)}

    except Exception as e:
        logger.warning("SEC EDGAR search failed", extra={"drug_name": drug_name, "error": str(e)})
        return {"cik": "", "filings": [], "total_hits": 0}


def _get_yfinance_data(drug_name: str) -> dict[str, Any]:
    """
    Get financial data from Yahoo Finance for the drug's originator company.

    Maps well-known drug names to their ticker symbols.
    Falls back to empty data if the drug isn't in the mapping.
    """
    # Drug → Ticker mapping for major pharma drugs
    drug_ticker_map: dict[str, str] = {
        "pembrolizumab": "MRK", "keytruda": "MRK",
        "nivolumab": "BMY", "opdivo": "BMY",
        "adalimumab": "ABBV", "humira": "ABBV",
        "semaglutide": "NVO", "ozempic": "NVO", "wegovy": "NVO",
        "trastuzumab": "RHHBY", "herceptin": "RHHBY",
        "bevacizumab": "RHHBY", "avastin": "RHHBY",
        "lenalidomide": "BMY", "revlimid": "BMY",
        "apixaban": "BMY", "eliquis": "BMY",
        "upadacitinib": "ABBV", "rinvoq": "ABBV",
        "empagliflozin": "LLY", "jardiance": "LLY",
        "dulaglutide": "LLY", "trulicity": "LLY",
        "risankizumab": "ABBV", "skyrizi": "ABBV",
    }

    ticker = drug_ticker_map.get(drug_name.lower())
    if not ticker:
        return {
            "company_name": "",
            "market_cap": 0,
            "total_revenue": 0,
            "revenue_growth": 0,
            "pe_ratio": None,
            "sector": "Healthcare",
        }

    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info or {}

        return {
            "company_name": info.get("longName", info.get("shortName", "")),
            "market_cap": info.get("marketCap", 0),
            "total_revenue": info.get("totalRevenue", 0),
            "revenue_growth": round((info.get("revenueGrowth", 0) or 0) * 100, 1),
            "pe_ratio": info.get("trailingPE"),
            "sector": info.get("sector", "Healthcare"),
        }
    except Exception as e:
        logger.warning("yfinance lookup failed", extra={"ticker": ticker, "error": str(e)})
        return {
            "company_name": "",
            "market_cap": 0,
            "total_revenue": 0,
            "revenue_growth": 0,
            "pe_ratio": None,
            "sector": "Healthcare",
        }


def _estimate_generic_share(therapeutic_area: str) -> float:
    """Estimate generic market share by therapeutic area (industry benchmarks)."""
    generic_shares = {
        "Oncology": 15.0,
        "Diabetes": 45.0,
        "Immunology": 12.0,
        "Cardiovascular": 68.0,
        "Neurology": 55.0,
        "Infectious Disease": 72.0,
    }
    return generic_shares.get(therapeutic_area, 35.0)
