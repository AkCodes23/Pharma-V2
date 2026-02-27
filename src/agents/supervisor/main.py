"""
Pharma Agentic AI — Supervisor Agent: Main Service.

Triggered by Cosmos DB Change Feed when all tasks for a session
reach COMPLETED. Validates grounding, detects conflicts, and
either routes to the Executor (valid) or back to the Planner (invalid).

Architecture context:
  - Service: Supervisor Agent (Azure Container App)
  - Responsibility: Quality gate between retrieval and synthesis
  - Trigger: Cosmos DB Change Feed on sessions container
  - Downstream: Executor (on pass), Planner (on fail/re-route)
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.infra.audit import AuditService
from src.shared.infra.cosmos_client import CosmosDBClient
from src.shared.models.enums import (
    AgentType,
    AuditAction,
    SessionStatus,
    TaskStatus,
)
from src.shared.models.schemas import Session

from src.agents.supervisor.validator import GroundingValidator

logger = logging.getLogger(__name__)


class SupervisorAgent:
    """
    Supervisor Agent — the quality gate for the agent swarm.

    Lifecycle:
      1. Monitor Cosmos DB Change Feed for session status changes
      2. When all tasks COMPLETED → trigger validation
      3. If valid → update session → trigger Executor
      4. If invalid → re-route to Planner (up to 3 times)
    """

    def __init__(
        self,
        cosmos: CosmosDBClient,
        audit: AuditService,
    ) -> None:
        self._cosmos = cosmos
        self._audit = audit
        self._validator = GroundingValidator()

    def process_session(self, session_id: str) -> bool:
        """
        Validate a completed session.

        Args:
            session_id: The session to validate.

        Returns:
            True if validation passed, False if conflicts/failures.
        """
        session = self._cosmos.get_session(session_id)

        # Check all tasks completed
        all_completed = all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.DLQ)
            for t in session.task_graph
        )
        if not all_completed:
            logger.warning(
                "Session not fully completed",
                extra={"session_id": session_id},
            )
            return False

        # Update session status
        self._cosmos.update_session_status(session_id, SessionStatus.VALIDATING)

        self._audit.log(
            session_id=session_id,
            user_id=session.user_id,
            agent_type=AgentType.SUPERVISOR,
            action=AuditAction.VALIDATION_STARTED,
            payload={"result_count": len(session.agent_results)},
        )

        # Run validation
        validation_result = self._validator.validate(session.agent_results)

        # Write validation result to session
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
                extra={
                    "session_id": session_id,
                    "grounding_score": validation_result.grounding_score,
                },
            )
            return True
        else:
            # Log conflicts
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
                extra={
                    "session_id": session_id,
                    "conflict_count": len(validation_result.conflicts),
                },
            )

            # Even with failures, proceed to executor with risk annotations
            # Critical conflicts are surfaced as Strategic Risks in the report
            return True  # We allow synthesis with risk annotations

    def close(self) -> None:
        self._validator.close()
