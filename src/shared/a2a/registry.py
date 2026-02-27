"""
Pharma Agentic AI — A2A Agent Registry.

Manages agent discovery and health-aware routing for the
Agent-to-Agent protocol.

Architecture context:
  - Service: Shared A2A protocol
  - Responsibility: Agent registration, heartbeat, capability-based discovery
  - Backends: Redis (fast heartbeat) + PostgreSQL (persistence)
  - Failure: Degrade to static agent config if registry unavailable
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.a2a.agent_card import AgentCard

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Agent registry for A2A capability-based discovery.

    Dual-backed:
      - Redis: Fast heartbeat tracking (TTL-based expiry)
      - PostgreSQL: Persistent agent metadata and capabilities

    Agents auto-register on startup and refresh heartbeat every 30s.
    """

    def __init__(self) -> None:
        self._redis = None
        self._postgres = None

    async def initialize(self) -> None:
        """Initialize Redis and PostgreSQL backends."""
        from src.shared.infra.redis_client import RedisClient
        from src.shared.infra.postgres_client import PostgresClient

        self._redis = RedisClient()
        self._postgres = PostgresClient()
        await self._postgres.initialize()
        logger.info("AgentRegistry initialized")

    async def register(self, card: AgentCard) -> None:
        """
        Register an agent in both Redis and PostgreSQL.

        Called on agent startup.
        """
        # Redis: fast heartbeat + capability lookup
        if self._redis:
            self._redis.register_agent_heartbeat(
                agent_id=card.agent_id,
                agent_info=card.to_dict(),
            )

        # PostgreSQL: persistent metadata
        if self._postgres:
            await self._postgres.register_agent(
                agent_id=card.agent_id,
                name=card.name,
                agent_type=card.agent_type,
                capabilities=card.capabilities,
                endpoint=card.endpoint,
                health_check=card.health_check,
            )

        logger.info(
            "Agent registered",
            extra={
                "agent_id": card.agent_id,
                "capabilities": card.capabilities,
            },
        )

    async def heartbeat(self, card: AgentCard) -> None:
        """Refresh agent heartbeat in Redis."""
        if self._redis:
            self._redis.register_agent_heartbeat(
                agent_id=card.agent_id,
                agent_info=card.to_dict(),
            )

    async def discover(self, capability: str) -> list[AgentCard]:
        """
        Discover active agents with a specific capability.

        Priority: Redis (fast) → PostgreSQL (persistent fallback).

        Args:
            capability: Required capability string.

        Returns:
            List of active AgentCards with the capability.
        """
        # Try Redis first (fast, includes heartbeat status)
        if self._redis:
            agents = self._redis.get_active_agents()
            matching = [
                AgentCard.from_dict(a)
                for a in agents
                if capability in a.get("capabilities", [])
            ]
            if matching:
                return matching

        # Fallback to PostgreSQL
        if self._postgres:
            rows = await self._postgres.get_agents_by_capability(capability)
            return [
                AgentCard(
                    agent_id=row["agent_id"],
                    name=row["name"],
                    agent_type=row["agent_type"],
                    capabilities=row.get("capabilities", []),
                    endpoint=row.get("endpoint", ""),
                    health_check=row.get("health_check", ""),
                )
                for row in rows
            ]

        return []

    async def discover_by_type(self, agent_type: str) -> list[AgentCard]:
        """Discover all active agents of a specific type."""
        if self._redis:
            agents = self._redis.get_active_agents()
            return [
                AgentCard.from_dict(a)
                for a in agents
                if a.get("agent_type") == agent_type
            ]
        return []

    async def get_all_active(self) -> list[AgentCard]:
        """Get all active (heartbeat-alive) agents."""
        if self._redis:
            agents = self._redis.get_active_agents()
            return [AgentCard.from_dict(a) for a in agents]
        return []

    async def deregister(self, agent_id: str) -> None:
        """Remove an agent from the registry (on shutdown)."""
        if self._redis:
            self._redis.client.delete(f"agent:{agent_id}")
            self._redis.client.srem("active_agents", agent_id)
        logger.info("Agent deregistered", extra={"agent_id": agent_id})
