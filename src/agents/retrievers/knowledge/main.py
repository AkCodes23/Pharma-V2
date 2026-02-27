"""
Pharma Agentic AI — Knowledge Retriever Agent.

Internal RAG agent for searching company documents via Azure AI Search.
"""

from __future__ import annotations

from typing import Any

from src.shared.models.enums import AgentType, PillarType
from src.shared.models.schemas import Citation, TaskNode

from src.agents.retrievers.base_retriever import BaseRetriever
from src.agents.retrievers.knowledge.tools import hybrid_search


class KnowledgeRetriever(BaseRetriever):
    """Knowledge pillar retriever — internal document RAG."""

    @property
    def agent_type(self) -> AgentType:
        return AgentType.KNOWLEDGE_RETRIEVER

    @property
    def pillar(self) -> PillarType:
        return PillarType.KNOWLEDGE

    def execute_tools(self, task: TaskNode) -> tuple[dict[str, Any], list[Citation]]:
        query = task.description
        drug_name = task.parameters.get("drug_name", "")

        search_query = f"{drug_name} {query}" if drug_name else query

        findings: dict[str, Any] = {
            "search_query": search_query,
            "internal_documents": [],
            "document_count": 0,
        }
        citations: list[Citation] = []

        try:
            results, search_cit = hybrid_search(search_query)
            findings["internal_documents"] = results
            findings["document_count"] = len(results)
            citations.append(search_cit)
        except Exception as e:
            findings["search_error"] = str(e)

        return findings, citations
