"""
Pharma Agentic AI — News Retriever Agent.

Real-time web intelligence retriever using Tavily search API.

Architecture context:
  - Service: News Retriever Agent (NEWS pillar)
  - Responsibility: Fetching biotech news, press releases, M&A not in DB
  - Data sources: Tavily Web Search API
  - Data ownership: Breaking news, press releases, deal activity

Efficiency: All 3 Tavily searches run concurrently via search_all().
"""

from __future__ import annotations

from typing import Any

from src.shared.models.enums import AgentType, PillarType
from src.shared.models.schemas import Citation, TaskNode

from src.agents.retrievers.base_retriever import BaseRetriever
from src.agents.retrievers.news.tools import close_http_client, search_all


class NewsRetriever(BaseRetriever):
    """News pillar retriever — real-time web intelligence."""

    @property
    def agent_type(self) -> AgentType:
        return AgentType.NEWS_RETRIEVER

    @property
    def pillar(self) -> PillarType:
        return PillarType.NEWS

    async def close(self) -> None:
        """Gracefully close the shared HTTP client."""
        await close_http_client()

    def execute_tools(self, task: TaskNode) -> tuple[dict[str, Any], list[Citation]]:
        """
        Execute web search tools for news intelligence.

        Dispatches all 3 Tavily searches concurrently via search_all(),
        reducing total wall time from ~90s → ~30s for 3 API calls.
        """
        import asyncio

        params = task.parameters
        drug_name = params.get("drug_name", params.get("ingredient", ""))
        company_name = params.get("company_name")
        target_market = params.get("target_market", "US")
        therapeutic_area = params.get("therapeutic_area")

        # Run all 3 searches concurrently in the event loop
        articles, releases, deals, citations = asyncio.get_event_loop().run_until_complete(
            search_all(
                drug_name=drug_name,
                target_market=target_market,
                company_name=company_name,
                therapeutic_area=therapeutic_area,
            )
        )

        # Extract high-signal articles (score > 0.7) as key signals
        key_signals = [
            {"type": "news", "title": a["title"], "url": a["url"]}
            for a in articles
            if a.get("score", 0) > 0.7
        ]
        if deals:
            key_signals.append({
                "type": "ma_activity",
                "deal_count": len(deals),
                "summary": f"{len(deals)} potential M&A/licensing deal(s) detected",
            })

        findings: dict[str, Any] = {
            "drug_name": drug_name,
            "target_market": target_market,
            "news_articles": articles,
            "press_releases": releases,
            "ma_deals": deals,
            "key_signals": key_signals,
        }

        return findings, citations
