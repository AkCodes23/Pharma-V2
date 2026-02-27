"""
Pharma Agentic AI — Commercial Retriever: Market Data Tools.

Deterministic API clients for market/financial data retrieval.
Uses mock data for MVP; designed for plug-in replacement with
licensed data feeds (IQVIA, Evaluate Pharma, GlobalData).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.shared.models.schemas import Citation

logger = logging.getLogger(__name__)


def _hash(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def get_market_data(
    drug_name: str,
    therapeutic_area: str,
    target_market: str,
) -> tuple[dict[str, Any], Citation]:
    """
    Retrieve market size, TAM, and growth data.

    Mock for MVP. In production, integrates with:
      - IQVIA MIDAS
      - Evaluate Pharma
      - GlobalData Pharma Intelligence
    """
    data = {
        "drug_name": drug_name,
        "therapeutic_area": therapeutic_area,
        "target_market": target_market,
        "total_addressable_market_usd": 2_100_000_000,
        "market_growth_cagr_pct": 12.3,
        "current_market_share_originator_pct": 78.5,
        "generic_market_share_pct": 21.5,
        "forecast_year": 2027,
        "market_trend": "GROWING",
        "key_competitors": [
            {"name": "Generic Pharma A", "market_share_pct": 8.2},
            {"name": "Generic Pharma B", "market_share_pct": 6.1},
            {"name": "Generic Pharma C", "market_share_pct": 4.8},
        ],
    }

    raw = json.dumps(data, default=str)
    citation = Citation(
        source_name="Market Intelligence Database",
        source_url=f"https://market-data.example.com/drugs/{drug_name}?market={target_market}",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash(raw),
        excerpt=f"[MOCK] TAM ${data['total_addressable_market_usd']:,.0f}, CAGR {data['market_growth_cagr_pct']}%",
    )

    return data, citation


def get_drug_revenue(
    drug_name: str,
) -> tuple[dict[str, Any], Citation]:
    """
    Retrieve historical and projected revenue for a drug.

    Mock for MVP.
    """
    data = {
        "drug_name": drug_name,
        "annual_revenue": [
            {"year": 2023, "revenue_usd": 25_000_000_000},
            {"year": 2024, "revenue_usd": 27_200_000_000},
            {"year": 2025, "revenue_usd": 28_500_000_000},
            {"year": 2026, "revenue_usd": 26_000_000_000, "note": "Patent cliff impact"},
        ],
        "peak_sales_usd": 28_500_000_000,
        "peak_year": 2025,
        "patent_cliff_impact_pct": -45.0,
    }

    raw = json.dumps(data, default=str)
    citation = Citation(
        source_name="Drug Revenue Database",
        source_url=f"https://revenue-data.example.com/drugs/{drug_name}",
        retrieved_at=datetime.now(timezone.utc),
        data_hash=_hash(raw),
        excerpt=f"[MOCK] Peak sales ${data['peak_sales_usd']:,.0f} in {data['peak_year']}",
    )

    return data, citation
