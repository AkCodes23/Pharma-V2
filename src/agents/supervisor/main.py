"""
Supervisor agent service.

Validates completed sessions and gates handoff to executor.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, HTTPException

from src.agents.supervisor.validator import GroundingValidator
from src.shared.bootstrap import bootstrap_agent
from src.shared.bootstrap.providers import create_session_store
from src.shared.infra.audit import AuditService
from src.shared.infra.auth import require_internal_api_key
from src.shared.models.enums import AgentType, AuditAction, SessionStatus, TaskStatus
from src.shared.ports.session_store import SessionStore

logger = logging.getLogger(__name__)


class SupervisorAgent:
    """Quality gate between retrieval and synthesis."""

    def __init__(self, cosmos: SessionStore, audit: AuditService) -> None:
        self._cosmos = cosmos
        self._audit = audit
        self._validator = GroundingValidator()

    def process_session(self, session_id: str) -> bool:
        """Validate a completed session."""
        session = self._cosmos.get_session(session_id)

        all_completed = all(t.status in (TaskStatus.COMPLETED, TaskStatus.DLQ) for t in session.task_graph)
        if not all_completed:
            logger.warning("Session not fully completed", extra={"session_id": session_id})
            return False

        self._cosmos.update_session_status(session_id, SessionStatus.VALIDATING)

        self._audit.log(
            session_id=session_id,
            user_id=session.user_id,
            agent_type=AgentType.SUPERVISOR,
            action=AuditAction.VALIDATION_STARTED,
            payload={"result_count": len(session.agent_results)},
        )

        validation_result = self._validator.validate(session.agent_results)
        self._cosmos.set_validation_result(session_id, validation_result)

        if validation_result.is_valid:
            self._audit.log(
                session_id=session_id,
                user_id=session.user_id,
                agent_type=AgentType.SUPERVISOR,
                action=AuditAction.VALIDATION_PASSED,
                payload={
                    "grounding_score": validation_result.grounding_score,
                    "conflict_count": len(validation_result.conflicts),
                },
            )
            logger.info(
                "Validation passed",
                extra={"session_id": session_id, "grounding_score": validation_result.grounding_score},
            )
            return True

        for conflict in validation_result.conflicts:
            self._audit.log(
                session_id=session_id,
                user_id=session.user_id,
                agent_type=AgentType.SUPERVISOR,
                action=AuditAction.CONFLICT_DETECTED,
                payload={
                    "conflict_type": conflict.conflict_type,
                    "severity": conflict.severity.value,
                    "pillars": [p.value for p in conflict.pillars_involved],
                },
            )

        self._audit.log(
            session_id=session_id,
            user_id=session.user_id,
            agent_type=AgentType.SUPERVISOR,
            action=AuditAction.VALIDATION_FAILED,
            payload={
                "grounding_score": validation_result.grounding_score,
                "conflict_count": len(validation_result.conflicts),
                "notes": validation_result.validation_notes,
            },
        )

        logger.warning(
            "Validation failed",
            extra={"session_id": session_id, "conflict_count": len(validation_result.conflicts)},
        )

        # Continue to synthesis with annotated risks for demo flow.
        return True

    def close(self) -> None:
        self._validator.close()


_cosmos: SessionStore | None = None
_audit: AuditService | None = None
_supervisor: SupervisorAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources."""
    global _cosmos, _audit, _supervisor

    bootstrap_agent(agent_name="supervisor-agent")
    _cosmos = create_session_store()
    _cosmos.ensure_containers()
    _audit = AuditService(_cosmos)
    _supervisor = SupervisorAgent(_cosmos, _audit)

    logger.info("Supervisor Agent started")
    yield

    if _supervisor:
        _supervisor.close()
    if _audit:
        _audit.shutdown()
    logger.info("Supervisor Agent stopped")


app = FastAPI(
    title="Pharma Agentic AI - Supervisor Agent",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "supervisor-agent"}


@app.post("/api/v1/sessions/{session_id}/validate")
async def validate_session(
    session_id: str,
    _: None = Depends(require_internal_api_key),
) -> dict[str, object]:
    if _supervisor is None or _cosmos is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        should_execute = _supervisor.process_session(session_id)
        session = _cosmos.get_session(session_id)
        return {
            "session_id": session_id,
            "validated": True,
            "ready_for_execution": bool(should_execute),
            "is_valid": session.validation.is_valid if session.validation else False,
            "grounding_score": session.validation.grounding_score if session.validation else 0.0,
            "conflict_count": len(session.validation.conflicts) if session.validation else 0,
        }
    except Exception as exc:
        logger.exception("Validation failed", extra={"session_id": session_id})
        raise HTTPException(status_code=500, detail=f"Validation failed: {type(exc).__name__}") from exc


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8001")))
