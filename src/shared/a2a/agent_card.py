"""
Pharma Agentic AI — A2A Agent Card.

Defines the AgentCard dataclass for agent capability discovery
in the Agent-to-Agent (A2A) protocol.

Architecture context:
  - Service: Shared A2A protocol
  - Responsibility: Agent identity and capability declaration
  - Pattern: Each agent publishes its AgentCard on startup
  - Discovery: Other agents query the registry for capabilities
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AgentCard:
    """
    Declares an agent's identity, capabilities, and interaction contract.

    Every agent in the swarm publishes an AgentCard on startup.
    Other agents use the registry to discover agents by capability.

    Example:
        card = AgentCard(
            agent_id="retriever-legal-001",
            name="Legal Retriever Agent",
            agent_type="retriever",
            capabilities=["patent_search", "fda_approval_lookup", "litigation_check"],
            input_schema={"query": "str", "drug_name": "str"},
            output_schema={"findings": "list", "citations": "list"},
            endpoint="http://retriever-legal:8001",
            health_check="http://retriever-legal:8001/health",
        )
    """
    agent_id: str
    name: str
    agent_type: str  # retriever, supervisor, executor, quality_evaluator, prompt_enhancer
    capabilities: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    endpoint: str = ""
    health_check: str = ""
    status: str = "ACTIVE"
    version: str = "0.1.0"
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for Redis/Postgres storage."""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "agent_type": self.agent_type,
            "capabilities": self.capabilities,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "endpoint": self.endpoint,
            "health_check": self.health_check,
            "status": self.status,
            "version": self.version,
            "registered_at": self.registered_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCard:
        """Deserialize from dict."""
        return cls(
            agent_id=data["agent_id"],
            name=data["name"],
            agent_type=data["agent_type"],
            capabilities=data.get("capabilities", []),
            input_schema=data.get("input_schema", {}),
            output_schema=data.get("output_schema", {}),
            endpoint=data.get("endpoint", ""),
            health_check=data.get("health_check", ""),
            status=data.get("status", "ACTIVE"),
            version=data.get("version", "0.1.0"),
        )

    def has_capability(self, capability: str) -> bool:
        """Check if this agent supports a specific capability."""
        return capability in self.capabilities
