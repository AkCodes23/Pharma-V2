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

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from src.agents.planner.orchestrator import PlannerOrchestrator
from src.agents.planner.publisher import TaskPublisher
from src.shared.bootstrap.providers import (
    create_decomposition_engine,
    create_session_store,
    create_task_publisher,
)
from src.shared.infra.audit import AuditService
from src.shared.infra.auth import is_admin_request, require_admin_user, require_authenticated_user
from src.shared.infra.cache_middleware import get_session_cache
from src.shared.infra.demo_auth import DemoAuthMiddleware
from src.shared.infra.rate_limit import rate_limiter
from src.shared.infra.redis_client import RedisClient
from src.shared.infra.telemetry import instrument_fastapi
from src.shared.infra.websocket import (
    start_websocket_manager,
    stop_websocket_manager,
    websocket_endpoint,
)
from src.shared.models.enums import AgentType, AuditAction
from src.shared.models.schemas import Session
from src.shared.ports.decomposition_engine import DecompositionEngine
from src.shared.ports.session_store import SessionStore
from src.shared.ports.task_bus import TaskBusPublisher

logger = logging.getLogger(__name__)

# ── Globals (initialized in lifespan) ──────────────────────
_cosmos: SessionStore | None = None
_publisher: TaskPublisher | None = None
_decomposer: DecompositionEngine | None = None
_redis: RedisClient | None = None
_audit: AuditService | None = None
_task_bus_publisher: TaskBusPublisher | None = None
_orchestrator: PlannerOrchestrator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: initialize and cleanup resources."""
    global _cosmos, _publisher, _decomposer, _redis, _audit, _task_bus_publisher, _orchestrator

    # Bootstrap: Key Vault → config → telemetry (ordered)
    from src.shared.bootstrap import bootstrap_agent
    settings = bootstrap_agent(agent_name="planner-agent")

    # Initialize infrastructure
    _cosmos = create_session_store()
    _cosmos.ensure_containers()
    _redis = RedisClient()
    _task_bus_publisher = create_task_publisher()
    _audit = AuditService(_cosmos)
    _publisher = TaskPublisher(_cosmos, _task_bus_publisher, _audit)
    _decomposer = create_decomposition_engine()
    if settings.provider.is_standalone_demo:
        _orchestrator = PlannerOrchestrator(_cosmos, _redis)
        await _orchestrator.start()
    await start_websocket_manager()

    logger.info("Planner Agent started")
    yield

    # Cleanup
    await stop_websocket_manager()
    if _decomposer:
        _decomposer.close()
    if _orchestrator:
        await _orchestrator.stop()
    if _audit:
        _audit.shutdown()
    if _task_bus_publisher:
        _task_bus_publisher.close()
    if _redis:
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

app.add_middleware(DemoAuthMiddleware)

# CORS for frontend — restricted origins (no wildcard in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Correlation-ID", "X-Demo-User", "X-User-Role"],
)

# OpenTelemetry instrumentation
instrument_fastapi(app)


# ── Request/Response Models ────────────────────────────────


class CreateSessionRequest(BaseModel):
    """Request body for creating a new query session."""

    query: str = Field(default="", max_length=2000, description="Natural-language strategic query")
    user_id: str | None = Field(default=None, description="User identifier")
    drug_name: str | None = Field(default=None)
    target_market: str | None = Field(default=None)
    priority: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode="after")
    def validate_payload(self) -> CreateSessionRequest:
        if self.query.strip() and len(self.query.strip()) >= 10:
            return self
        if self.drug_name and len(self.drug_name.strip()) >= 2:
            return self
        raise ValueError("Provide either a detailed query (>=10 chars) or a valid drug_name")


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
    drug_name: str | None = None
    target_market: str | None = None
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


@app.post(
    "/api/v1/sessions",
    response_model=CreateSessionResponse,
    status_code=201,
    dependencies=[Depends(rate_limiter)],
)
async def create_session(
    request: CreateSessionRequest,
    req: Request,
    authenticated_user: str = Depends(require_authenticated_user),
) -> CreateSessionResponse:
    """
    Create a new query session.

    Decomposes the query into a task graph and publishes
    sub-tasks to Azure Service Bus for parallel execution.
    """
    if not _decomposer or not _publisher or not _cosmos or not _audit:
        raise HTTPException(status_code=503, detail="Service not ready")

    session_id = str(uuid4())
    correlation_id = req.headers.get("x-correlation-id", str(uuid4()))

    try:
        effective_query = request.query
        effective_user_id = request.user_id or authenticated_user

        # MCP compatibility: if only structured fields are provided,
        # synthesize an execution query for decomposition.
        if not effective_query.strip() and request.drug_name:
            market = request.target_market or "global"
            effective_query = f"Analyze {request.drug_name} market entry strategy in {market}"

        # 1. Decompose intent
        query_params, tasks = _decomposer.decompose(
            query=effective_query,
            session_id=session_id,
        )

        # 2. Publish to Service Bus
        session = _publisher.publish(
            query=effective_query,
            user_id=effective_user_id,
            parameters=query_params,
            tasks=tasks,
            session_id=session_id,
            correlation_id=correlation_id,
        )

        # 3. Audit the query submission
        _audit.log(
            session_id=session_id,
            user_id=effective_user_id,
            agent_type=AgentType.PLANNER,
            action=AuditAction.QUERY_SUBMITTED,
            payload={"query": effective_query},
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
async def get_session(
    session_id: str,
    req: Request,
    authenticated_user: str = Depends(require_authenticated_user),
) -> SessionStatusResponse:
    """Get the current status of a query session."""
    if not _cosmos:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        cache = get_session_cache()
        cached = cache.get_cached_session(session_id)
        if cached is not None:
            session = Session.model_validate(cached)
        else:
            session = _cosmos.get_session(session_id)
            cache.cache_session(session_id, session.model_dump(mode="json"))

        if session.user_id != authenticated_user and not is_admin_request(req):
            raise HTTPException(status_code=403, detail="Access denied for session")

        return SessionStatusResponse(
            session_id=session.id,
            status=session.status.value,
            drug_name=session.parameters.drug_name,
            target_market=session.parameters.target_market,
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
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get session", extra={"session_id": session_id})
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}") from e


@app.get("/api/v1/sessions")
async def list_sessions(
    req: Request,
    drug_name: str = Query(default=""),
    user_id: str = Query(default=""),
    status: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    authenticated_user: str = Depends(require_authenticated_user),
) -> dict[str, Any]:
    """List sessions with optional filters and pagination."""
    if not _cosmos:
        raise HTTPException(status_code=503, detail="Service not ready")

    if not is_admin_request(req):
        user_id = authenticated_user

    sessions, total = _cosmos.list_sessions(
        drug_name=drug_name,
        user_id=user_id,
        status=status,
        limit=limit,
        offset=offset,
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "sessions": [
            {
                "session_id": s.id,
                "drug_name": s.parameters.drug_name,
                "target_market": s.parameters.target_market,
                "status": s.status.value,
                "decision": s.decision.value if s.decision else None,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
            }
            for s in sessions
        ],
    }


@app.get("/api/v1/sessions/{session_id}/report")
async def get_session_report(
    session_id: str,
    req: Request,
    format: str = Query(default="pdf"),
    authenticated_user: str = Depends(require_authenticated_user),
) -> dict[str, Any]:
    """Fetch report payload or URL for a completed session."""
    if not _cosmos:
        raise HTTPException(status_code=503, detail="Service not ready")

    session = _cosmos.get_session(session_id)
    if session.user_id != authenticated_user and not is_admin_request(req):
        raise HTTPException(status_code=403, detail="Access denied for session")
    requested_format = format.lower()

    if requested_format == "pdf":
        if not session.report_url:
            raise HTTPException(status_code=404, detail="Report not generated yet")
        return {
            "session_id": session.id,
            "report_url": session.report_url,
            "generated_at": session.completed_at.isoformat() if session.completed_at else None,
            "file_size_kb": None,
        }

    if requested_format == "summary":
        return {
            "session_id": session.id,
            "query": session.query,
            "decision": session.decision.value if session.decision else None,
            "decision_rationale": session.decision_rationale,
            "grounding_score": session.validation.grounding_score if session.validation else None,
            "conflict_count": len(session.validation.conflicts) if session.validation else 0,
            "report_url": session.report_url,
        }

    if requested_format == "json":
        return {
            "session_id": session.id,
            "query": session.query,
            "status": session.status.value,
            "decision": session.decision.value if session.decision else None,
            "decision_rationale": session.decision_rationale,
            "validation": session.validation.model_dump() if session.validation else None,
            "agent_results": [r.model_dump() for r in session.agent_results],
            "report_url": session.report_url,
        }

    raise HTTPException(status_code=400, detail="format must be one of: pdf, json, summary")


@app.get("/audit")
async def list_audit(
    limit: int = Query(default=100, ge=1, le=500),
    session_id: str = Query(default=""),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    """List recent audit entries for admin UI / diagnostics."""
    if not _cosmos:
        raise HTTPException(status_code=503, detail="Service not ready")

    entries = _cosmos.list_audit_entries(limit=limit, session_id=session_id)
    return {"entries": [entry.model_dump(mode="json") for entry in entries]}


@app.get("/metrics/agents")
async def get_agent_metrics(_: str = Depends(require_admin_user)) -> dict[str, Any]:
    """Compute lightweight agent metrics from recent sessions."""
    if not _cosmos:
        raise HTTPException(status_code=503, detail="Service not ready")

    sessions, _ = _cosmos.list_sessions(limit=200, offset=0)
    aggregates: dict[str, dict[str, float | int]] = {}

    for session in sessions:
        for result in session.agent_results:
            agent = result.agent_type.value
            bucket = aggregates.setdefault(
                agent,
                {"total_latency_ms": 0, "total_invocations": 0, "success_count": 0},
            )
            bucket["total_latency_ms"] += int(result.execution_time_ms)
            bucket["total_invocations"] += 1

            has_error = any(k.endswith("_error") for k in result.findings)
            if not has_error:
                bucket["success_count"] += 1

    metrics = []
    for agent, bucket in aggregates.items():
        total_invocations = int(bucket["total_invocations"])
        if total_invocations == 0:
            continue
        avg_latency = int(bucket["total_latency_ms"]) / total_invocations
        success_rate = (int(bucket["success_count"]) / total_invocations) * 100
        metrics.append(
            {
                "agent": agent,
                "avg_latency_ms": round(avg_latency, 2),
                "success_rate": round(success_rate, 2),
                "total_invocations": total_invocations,
            }
        )

    metrics.sort(key=lambda m: m["agent"])
    return {"metrics": metrics}


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for container orchestration."""
    return {"status": "healthy", "service": "planner-agent"}


@app.websocket("/ws/sessions/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time session updates."""
    await websocket_endpoint(websocket, session_id)
