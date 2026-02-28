"""
Pharma Agentic AI — A2A Capability Contracts.

Typed contracts that describe what each agent capability requires,
produces, and guarantees. The Planner negotiates using contracts
before delegating — ensuring type-safe, SLA-aware routing.

Architecture context:
  - Service: Shared A2A protocol
  - Responsibility: Capability schema definition and validation
  - Upstream: Planner (uses contracts to pick best agent)
  - Downstream: Agent registry (serves contracts on negotiation)
  - Pattern: Schema-first delegation (validate before call)

Contract lifecycle:
  1. Agent publishes its CapabilityContract on startup → registry
  2. Planner fetches contracts for a required capability
  3. Planner validates its input against contract.input_schema
  4. Planner selects the agent with lowest cost + SLA within budget
  5. Planner delegates via AgentMesh using the selected contract
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────

class SLATier(str, Enum):
    """Agent Service Level Agreement tiers."""
    REALTIME = "realtime"    # < 2s  — direct HTTP only
    FAST = "fast"            # < 10s — direct HTTP preferred
    STANDARD = "standard"   # < 60s — Kafka acceptable
    BATCH = "batch"          # < 5min — Kafka only


class CapabilityCategory(str, Enum):
    """High-level capability categories for discovery."""
    RETRIEVAL = "retrieval"          # Fetch data from external sources
    ANALYSIS = "analysis"           # Process and evaluate data
    SYNTHESIS = "synthesis"         # Generate reports/summaries
    ORCHESTRATION = "orchestration" # Coordinate other agents
    MONITORING = "monitoring"       # Health/status observation


# ── Schema primitives ────────────────────────────────────

class FieldSchema(BaseModel):
    """Schema definition for a single input/output field."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Field name")
    type: str = Field(..., description="Python type hint string, e.g. 'str', 'list[str]', 'dict'")
    required: bool = Field(default=True)
    description: str = Field(default="")
    example: Any = Field(default=None)


class ContractSchema(BaseModel):
    """Input or output schema for a capability."""
    model_config = ConfigDict(extra="forbid")

    fields: list[FieldSchema] = Field(default_factory=list)
    description: str = Field(default="")

    def validate_data(self, data: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Validate a data dict against this schema.

        Returns:
            Tuple of (is_valid: bool, errors: list[str]).
        """
        errors: list[str] = []
        required_fields = {f.name for f in self.fields if f.required}
        provided_keys = set(data.keys())

        missing = required_fields - provided_keys
        for field in missing:
            errors.append(f"Missing required field: '{field}'")

        return len(errors) == 0, errors

    def to_json_schema(self) -> dict[str, Any]:
        """Export as JSON Schema draft-7 format."""
        properties: dict[str, Any] = {}
        required: list[str] = []

        for field in self.fields:
            properties[field.name] = {
                "type": field.type,
                "description": field.description,
            }
            if field.example is not None:
                properties[field.name]["example"] = field.example
            if field.required:
                required.append(field.name)

        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "description": self.description,
            "properties": properties,
            "required": required,
            "additionalProperties": True,
        }


# ── Capability Contract ──────────────────────────────────

class CapabilityContract(BaseModel):
    """
    A typed contract describing a single agent capability.

    Published by each agent on startup. Used by the Planner to:
    - Discover which agents can fulfill a task
    - Validate input data before delegation
    - Select the optimal agent based on SLA and cost
    - Negotiate capability terms (e.g., accept partial results)
    """
    model_config = ConfigDict(extra="forbid")

    # Identity
    capability_id: str = Field(..., description="Unique capability identifier, e.g. 'fda_drug_lookup'")
    capability_name: str = Field(..., description="Human-readable name")
    category: CapabilityCategory

    # Schemas
    input_schema: ContractSchema = Field(default_factory=ContractSchema)
    output_schema: ContractSchema = Field(default_factory=ContractSchema)

    # SLA
    sla_tier: SLATier = Field(default=SLATier.STANDARD)
    max_latency_ms: int = Field(default=30_000, description="Guaranteed max response time in ms")
    supports_streaming: bool = Field(default=False, description="Can stream partial results via WebSocket")
    supports_partial: bool = Field(default=True, description="Can return partial results on timeout")

    # Cost
    estimated_token_cost: int = Field(default=0, description="Estimated LLM tokens consumed per call")
    estimated_api_calls: int = Field(default=1, description="Estimated external API calls per execution")

    # Routing
    preferred_transport: str = Field(
        default="http",
        description="Preferred routing: 'http' (direct mesh) or 'kafka' (broker)",
    )
    invoke_endpoint: str = Field(default="", description="Direct HTTP invoke URL for mesh routing")

    @field_validator("capability_id")
    @classmethod
    def validate_capability_id(cls, v: str) -> str:
        if " " in v:
            raise ValueError("capability_id must not contain spaces — use underscores")
        return v.lower()

    def validate_input(self, data: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate input data against this contract's input schema."""
        return self.input_schema.validate_data(data)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for Redis storage / network transport."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityContract:
        """Deserialize from Redis / network."""
        return cls(**data)


# ── Pre-defined contracts for all pharma agents ──────────

def make_retriever_contract(
    pillar: str,
    capability_id: str,
    capability_name: str,
    invoke_endpoint: str,
    estimated_token_cost: int = 0,
    estimated_api_calls: int = 2,
    sla_tier: SLATier = SLATier.FAST,
) -> CapabilityContract:
    """Factory for standard retriever contracts (all share the same schema)."""
    return CapabilityContract(
        capability_id=capability_id,
        capability_name=capability_name,
        category=CapabilityCategory.RETRIEVAL,
        input_schema=ContractSchema(
            description=f"Input for {pillar} retrieval",
            fields=[
                FieldSchema(name="drug_name", type="str", required=True,
                            description="Drug INN or brand name", example="Semaglutide"),
                FieldSchema(name="target_market", type="str", required=False,
                            description="Target market code", example="US"),
                FieldSchema(name="session_id", type="str", required=True,
                            description="Session UUID for correlation"),
            ],
        ),
        output_schema=ContractSchema(
            description=f"Output from {pillar} retrieval",
            fields=[
                FieldSchema(name="findings", type="dict", required=True, description="Structured findings"),
                FieldSchema(name="citations", type="list", required=True, description="Source citations"),
                FieldSchema(name="confidence", type="float", required=True, description="0.0-1.0"),
            ],
        ),
        sla_tier=sla_tier,
        max_latency_ms=30_000,
        supports_streaming=True,
        supports_partial=True,
        estimated_token_cost=estimated_token_cost,
        estimated_api_calls=estimated_api_calls,
        preferred_transport="http",
        invoke_endpoint=invoke_endpoint,
    )


# Registry of all built-in pharma capability contracts
PHARMA_CONTRACTS: dict[str, CapabilityContract] = {
    "fda_drug_retrieval": make_retriever_contract(
        pillar="LEGAL",
        capability_id="fda_drug_retrieval",
        capability_name="FDA Drug Database Retrieval",
        invoke_endpoint="http://retriever-legal:8003/invoke",
        estimated_api_calls=3,
        sla_tier=SLATier.FAST,
    ),
    "clinical_trials_retrieval": make_retriever_contract(
        pillar="CLINICAL",
        capability_id="clinical_trials_retrieval",
        capability_name="ClinicalTrials.gov Retrieval",
        invoke_endpoint="http://retriever-clinical:8004/invoke",
        estimated_api_calls=4,
        sla_tier=SLATier.FAST,
    ),
    "commercial_market_retrieval": make_retriever_contract(
        pillar="COMMERCIAL",
        capability_id="commercial_market_retrieval",
        capability_name="Commercial Market Intelligence Retrieval",
        invoke_endpoint="http://retriever-commercial:8005/invoke",
        estimated_api_calls=3,
        sla_tier=SLATier.STANDARD,
    ),
    "biotech_news_retrieval": make_retriever_contract(
        pillar="NEWS",
        capability_id="biotech_news_retrieval",
        capability_name="Real-time Biotech News (Tavily)",
        invoke_endpoint="http://retriever-news:8007/invoke",
        estimated_api_calls=3,
        sla_tier=SLATier.FAST,
    ),
    "quality_evaluation": CapabilityContract(
        capability_id="quality_evaluation",
        capability_name="Report Quality Evaluation",
        category=CapabilityCategory.ANALYSIS,
        input_schema=ContractSchema(
            fields=[
                FieldSchema(name="session_id", type="str", required=True),
                FieldSchema(name="report_draft", type="dict", required=True),
                FieldSchema(name="citations", type="list", required=True),
            ],
        ),
        output_schema=ContractSchema(
            fields=[
                FieldSchema(name="grounding_score", type="float", required=True),
                FieldSchema(name="quality_score", type="float", required=True),
                FieldSchema(name="issues", type="list", required=False),
            ],
        ),
        sla_tier=SLATier.FAST,
        max_latency_ms=15_000,
        estimated_token_cost=2000,
        preferred_transport="http",
        invoke_endpoint="http://quality-evaluator:8008/invoke",
    ),
}


def get_contract(capability_id: str) -> CapabilityContract | None:
    """Look up a built-in contract by capability_id."""
    return PHARMA_CONTRACTS.get(capability_id)


def list_contracts() -> list[dict[str, Any]]:
    """List all built-in capability contracts as dicts."""
    return [c.to_dict() for c in PHARMA_CONTRACTS.values()]
