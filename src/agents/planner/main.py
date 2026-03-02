"""
Pharma Agentic AI — Planner Agent: FastAPI Application.

Entry point for the Planner Agent microservice. Exposes:
  - POST /api/v1/sessions — Create a new query session
  - GET /api/v1/sessions/{session_id} — Get session status
  - GET /health — Health check

Architecture context:
  - Service: Planner Agent (Azure Container App)
  - Responsibility: Accepts queries, decomposes intent, publishes tasks
  - Upstream: Azure API Management
  - Downstream: Service Bus, Cosmos DB
  - Scaling: 1 to N instances via ACA
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.agents.planner.decomposer import IntentDecomposer
from src.agents.planner.publisher import TaskPublisher
from src.shared.infra.audit import AuditService
from src.shared.infra.cache_middleware import get_session_cache
from src.shared.infra.cosmos_client import CosmosDBClient
from src.shared.infra.rate_limit import rate_limiter
from src.shared.infra.redis_client import RedisClient
from src.shared.infra.servicebus_client import ServiceBusPublisher
from src.shared.infra.telemetry import instrument_fastapi, setup_telemetry
from src.shared.infra.websocket import websocket_endpoint
from src.shared.models.enums import AgentType, AuditAction

logger = logging.getLogger(__name__)

# ── Globals (initialized in lifespan) ──────────────────────
_cosmos: CosmosDBClient | None = None
_publisher: TaskPublisher | None = None
_decomposer: IntentDecomposer | None = None
_redis: RedisClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: initialize and cleanup resources."""
    global _cosmos, _publisher, _decomposer, _redis

    # Bootstrap: Key Vault → config → telemetry (ordered)
    from src.shared.bootstrap import bootstrap_agent
    bootstrap_agent(agent_name="planner-agent")

    # Initialize infrastructure
    _cosmos = CosmosDBClient()
    _cosmos.ensure_containers()
    _redis = RedisClient()
    servicebus = ServiceBusPublisher()
    audit = AuditService(_cosmos)
    _publisher = TaskPublisher(_cosmos, servicebus, audit)
    _decomposer = IntentDecomposer()

    logger.info("Planner Agent started")
    yield

    # Cleanup
    _decomposer.close()
    servicebus.close()
    _redis.close()
    logger.info("Planner Agent stopped")


# Allowed CORS origins — restrict in production
_CORS_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:3001",
).split(",")

app = FastAPI(
    title="Pharma Agentic AI — Planner Agent",
    description="Decomposes pharmaceutical strategic queries into multi-agent task graphs.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for frontend — restricted origins (no wildcard in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Correlation-ID"],
)

# OpenTelemetry instrumentation
instrument_fastapi(app)


# ── Request/Response Models ────────────────────────────────


class CreateSessionRequest(BaseModel):
    """Request body for creating a new query session."""

    query: str = Field(..., min_length=10, max_length=2000, description="Natural-language strategic query")
    user_id: str = Field(default="anonymous", description="Azure Entra ID object ID")


class TaskNodeResponse(BaseModel):
    """Simplified task node for API response."""

    task_id: str
    pillar: str
    description: str
    status: str


class CreateSessionResponse(BaseModel):
    """Response for session creation."""

    session_id: str
    status: str
    task_count: int
    tasks: list[TaskNodeResponse]
    websocket_url: str


class SessionStatusResponse(BaseModel):
    """Response for session status query."""

    session_id: str
    status: str
    query: str
    task_graph: list[TaskNodeResponse]
    agent_results: list[dict[str, Any]]
    validation: dict[str, Any] | None
    decision: str | None
    decision_rationale: str | None
    report_url: str | None
    created_at: str
    updated_at: str


# ── Endpoints ──────────────────────────────────────────────


@app.post("/api/v1/sessions", response_model=CreateSessionResponse, status_code=201, dependencies=[Depends(rate_limiter)])
async def create_session(request: CreateSessionRequest, req: Request) -> CreateSessionResponse:
    """
    Create a new query session.

    Decomposes the query into a task graph and publishes
    sub-tasks to Azure Service Bus for parallel execution.
    """
    if not _decomposer or not _publisher or not _cosmos:
        raise HTTPException(status_code=503, detail="Service not ready")

    session_id = str(uuid4())
    correlation_id = req.headers.get("x-correlation-id", str(uuid4()))

    try:
        # 1. Decompose intent
        query_params, tasks = _decomposer.decompose(
            query=request.query,
            session_id=session_id,
        )

        # 2. Publish to Service Bus
        session = _publisher.publish(
            query=request.query,
            user_id=request.user_id,
            parameters=query_params,
            tasks=tasks,
            session_id=session_id,
            correlation_id=correlation_id,
        )

        # 3. Audit the query submission
        audit = AuditService(_cosmos)
        audit.log(
            session_id=session_id,
            user_id=request.user_id,
            agent_type=AgentType.PLANNER,
            action=AuditAction.QUERY_SUBMITTED,
            payload={"query": request.query},
            ip_address=req.client.host if req.client else None,
            correlation_id=correlation_id,
        )

        return CreateSessionResponse(
            session_id=session_id,
            status=session.status.value,
            task_count=len(tasks),
            tasks=[
                TaskNodeResponse(
                    task_id=t.task_id,
                    pillar=t.pillar.value,
                    description=t.description,
                    status=t.status.value,
                )
                for t in tasks
            ],
            websocket_url=f"/ws/sessions/{session_id}",
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to create session", extra={"session_id": session_id})
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}") from e


@app.get("/api/v1/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_session(session_id: str) -> SessionStatusResponse:
    """Get the current status of a query session."""
    if not _cosmos:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        session = _cosmos.get_session(session_id)
        return SessionStatusResponse(
            session_id=session.id,
            status=session.status.value,
            query=session.query,
            task_graph=[
                TaskNodeResponse(
                    task_id=t.task_id,
                    pillar=t.pillar.value,
                    description=t.description,
                    status=t.status.value,
                )
                for t in session.task_graph
            ],
            agent_results=[r.model_dump() for r in session.agent_results],
            validation=session.validation.model_dump() if session.validation else None,
            decision=session.decision.value if session.decision else None,
            decision_rationale=session.decision_rationale,
            report_url=session.report_url,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
        )
    except Exception as e:
        logger.exception("Failed to get session", extra={"session_id": session_id})
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}") from e


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for container orchestration."""
    return {"status": "healthy", "service": "planner-agent"}


@app.websocket("/ws/sessions/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time session updates."""
    await websocket_endpoint(websocket, session_id)
