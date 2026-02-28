"""
Pharma Agentic AI — Agent /invoke endpoint.

Direct HTTP mesh invocation endpoint added to every agent service.
The AgentMesh router calls `POST /invoke` to bypass Kafka for
low-latency REALTIME/FAST SLA-tier tasks.

Architecture context:
  - Pattern: Request-Response (synchronous, timeout-bounded)
  - Caller: AgentMesh (from Planner/Supervisor)
  - Authentication: X-Internal-Service header (internal mesh only)
  - Not exposed externally (only within Docker network)

Include this router in every FastAPI agent's main.py:

    from src.shared.a2a.invoke_endpoint import invoke_router
    app.include_router(invoke_router)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

invoke_router = APIRouter(tags=["mesh"])

# ── Request / Response models ─────────────────────────────

class AgentInvokeRequest(BaseModel):
    """Inbound request from the AgentMesh router."""
    session_id: str = Field(..., description="Session UUID")
    capability_id: str = Field(..., description="Capability being invoked")
    input_data: dict[str, Any] = Field(default_factory=dict)
    sender_id: str = Field(..., description="Requesting agent ID")
    correlation_id: str | None = Field(default=None)
    deadline_ms: int = Field(default=30_000, ge=1_000, le=120_000)


class AgentInvokeResponse(BaseModel):
    """Response from direct agent invocation."""
    success: bool
    agent_id: str
    capability_id: str
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    latency_ms: int = 0


# ── Auth guard ────────────────────────────────────────────

def _verify_internal(x_internal_service: str = Header(default="")) -> None:
    """
    Verify the caller is an internal mesh service (not external).
    Checks the X-Internal-Service header injected by the mesh router.
    """
    if not x_internal_service:
        raise HTTPException(status_code=403, detail="Mesh-only endpoint. X-Internal-Service required.")


# ── Endpoint ──────────────────────────────────────────────

@invoke_router.post(
    "/invoke",
    response_model=AgentInvokeResponse,
    summary="Direct mesh invocation",
    description="Called by the AgentMesh router for low-latency A2A. Not for external use.",
)
async def invoke(
    request: AgentInvokeRequest,
    _: None = Depends(_verify_internal),
) -> AgentInvokeResponse:
    """
    Execute a capability synchronously and return the result.

    The AgentMesh timeout is enforced at the caller level.
    This endpoint should complete within request.deadline_ms.
    """
    start = time.perf_counter_ns()
    agent_id = "unknown"

    try:
        # Import the agent's execute function dynamically.
        # Each agent service sets AGENT_MODULE env var pointing to its executor.
        import importlib
        import os

        agent_module = os.getenv("AGENT_MODULE", "")
        if not agent_module:
            raise RuntimeError("AGENT_MODULE env var not set — cannot dispatch invoke")

        mod = importlib.import_module(agent_module)
        agent_id = getattr(mod, "AGENT_ID", agent_module)

        # Each agent module must expose `async def handle_invoke(capability_id, input_data)`
        result = await mod.handle_invoke(
            capability_id=request.capability_id,
            input_data=request.input_data,
            session_id=request.session_id,
        )

        latency_ms = (time.perf_counter_ns() - start) // 1_000_000
        logger.info(
            "Invoke completed",
            extra={
                "capability_id": request.capability_id,
                "session_id": request.session_id,
                "latency_ms": latency_ms,
            },
        )

        return AgentInvokeResponse(
            success=True,
            agent_id=agent_id,
            capability_id=request.capability_id,
            result=result,
            latency_ms=latency_ms,
        )

    except Exception as e:
        latency_ms = (time.perf_counter_ns() - start) // 1_000_000
        logger.error(
            "Invoke failed",
            extra={
                "capability_id": request.capability_id,
                "error": str(e),
                "latency_ms": latency_ms,
            },
        )
        return AgentInvokeResponse(
            success=False,
            agent_id=agent_id,
            capability_id=request.capability_id,
            error=str(e),
            latency_ms=latency_ms,
        )
