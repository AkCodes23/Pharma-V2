"""
Pharma Agentic AI — Long-Term Memory (PostgreSQL-Backed).

Persistent user knowledge: preferences, query patterns, and
decision history. Survives sessions and enables personalization.

Architecture context:
  - Service: Shared memory layer (Context Engineering)
  - Responsibility: Cross-session user knowledge
  - Backend: PostgreSQL (user_memory table)
  - Data ownership: Persistent, user-scoped
  - Failure: Non-critical — missing preferences degrade personalization only
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LongTermMemory:
    """
    PostgreSQL-backed long-term memory for user personalization.

    Stores and retrieves:
      1. User preferences (e.g., preferred markets, therapeutic areas)
      2. Query patterns (e.g., frequently analyzed drugs)
      3. Decision history (past GO/NO-GO decisions for context)

    Used by the Planner Agent to personalize query decomposition.
    """

    def __init__(self) -> None:
        self._postgres = None

    async def initialize(self) -> None:
        """Initialize PostgreSQL backend."""
        from src.shared.infra.postgres_client import PostgresClient
        self._postgres = PostgresClient()
        await self._postgres.initialize()
        logger.info("LongTermMemory initialized")

    async def remember(self, user_id: str, memory_type: str, key: str, value: dict[str, Any]) -> None:
        """
        Store a memory entry.

        Upserts: if the same (user_id, memory_type, key) exists,
        it's updated and access_count is incremented.

        Args:
            user_id: Azure Entra ID.
            memory_type: Category ('preference', 'query_pattern', 'decision_history').
            key: Memory key (e.g., 'preferred_market', 'last_drug_analyzed').
            value: Memory value (JSON-serializable dict).
        """
        if not self._postgres:
            return
        await self._postgres.store_user_memory(user_id, memory_type, key, value)

    async def recall(
        self, user_id: str, memory_type: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """
        Retrieve user memories.

        Args:
            user_id: Azure Entra ID.
            memory_type: Optional filter by category.
            limit: Max entries to return.

        Returns:
            List of memory entries, most recently accessed first.
        """
        if not self._postgres:
            return []
        return await self._postgres.get_user_memories(user_id, memory_type, limit)

    async def recall_formatted(self, user_id: str) -> str:
        """
        Get user memories formatted for LLM prompt injection.

        Returns a string like:
            User preferences: India market, oncology focus
            Recent queries: Keytruda (3x), Opdivo (2x)
            Past decisions: Keytruda India → GO, Opdivo EU → NO_GO
        """
        memories = await self.recall(user_id)
        if not memories:
            return ""

        sections: list[str] = []
        for mem in memories:
            key = mem.get("key", "")
            value = mem.get("value", "")
            memory_type = mem.get("memory_type", "unknown")
            sections.append(f"[{memory_type}] {key}: {value}")

        return "\n".join(sections)

    async def learn_from_session(
        self, user_id: str, drug_name: str, market: str, decision: str, query: str
    ) -> None:
        """
        Extract and store learnings from a completed session.

        Called by the Executor after a session completes.
        """
        # Store query pattern
        await self.remember(
            user_id=user_id,
            memory_type="query_pattern",
            key=f"drug:{drug_name}",
            value={"drug": drug_name, "market": market, "query": query},
        )

        # Store decision history
        await self.remember(
            user_id=user_id,
            memory_type="decision_history",
            key=f"decision:{drug_name}:{market}",
            value={"drug": drug_name, "market": market, "decision": decision},
        )

        # Update preferred market
        await self.remember(
            user_id=user_id,
            memory_type="preference",
            key="preferred_market",
            value={"market": market},
        )
