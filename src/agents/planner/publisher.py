"""
Pharma Agentic AI — Planner Agent: Task Publisher.

Takes a decomposed TaskGraph and publishes each TaskNode to the
appropriate Azure Service Bus topic. Creates the Cosmos DB session
and writes audit entries for each published task.

Architecture context:
  - Service: Planner Agent
  - Responsibility: Session creation + task distribution
  - Upstream: IntentDecomposer
  - Downstream: Service Bus → Retriever Agents
  - Data ownership: Session initialization
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.infra.audit import AuditService
from src.shared.infra.cosmos_client import CosmosDBClient
from src.shared.infra.servicebus_client import ServiceBusPublisher
from src.shared.models.enums import AgentType, AuditAction, SessionStatus
from src.shared.models.schemas import (
    QueryParameters,
    ServiceBusMessage,
    Session,
    TaskNode,
)

logger = logging.getLogger(__name__)


class TaskPublisher:
    """
    Publishes a decomposed task graph to Azure Service Bus.

    Orchestrates:
      1. Create session in Cosmos DB
      2. Publish each task to the correct Service Bus topic
      3. Write audit entries for every action
    """

    def __init__(
        self,
        cosmos: CosmosDBClient,
        servicebus: ServiceBusPublisher,
        audit: AuditService,
    ) -> None:
        self._cosmos = cosmos
        self._servicebus = servicebus
        self._audit = audit

    def publish(
        self,
        query: str,
        user_id: str,
        parameters: QueryParameters,
        tasks: list[TaskNode],
        session_id: str,
        correlation_id: str | None = None,
    ) -> Session:
        """
        Create a session and publish all tasks to Service Bus.

        Args:
            query: Original user query.
            user_id: Azure Entra ID of the requesting user.
            parameters: Structured query parameters.
            tasks: List of decomposed TaskNode objects.
            session_id: Pre-generated session ID.
            correlation_id: OpenTelemetry trace ID.

        Returns:
            The created Session object.

        Raises:
            Exception: If session creation or task publishing fails.
        """
        # 1. Create session in Cosmos DB
        session = Session(
            id=session_id,
            user_id=user_id,
            query=query,
            parameters=parameters,
            status=SessionStatus.PLANNING,
            task_graph=tasks,
        )
        self._cosmos.create_session(session)

        self._audit.log(
            session_id=session_id,
            user_id=user_id,
            agent_type=AgentType.PLANNER,
            action=AuditAction.SESSION_CREATED,
            payload={"query": query, "task_count": len(tasks)},
            correlation_id=correlation_id,
        )

        # 2. Update session status to RETRIEVING
        self._cosmos.update_session_status(session_id, SessionStatus.RETRIEVING)

        # 3. Publish each task to Service Bus
        published_count = 0
        for task in tasks:
            try:
                message = ServiceBusMessage(
                    session_id=session_id,
                    task=task,
                    correlation_id=correlation_id or "",
                )
                self._servicebus.publish_task(message)
                published_count += 1

                self._audit.log(
                    session_id=session_id,
                    user_id=user_id,
                    agent_type=AgentType.PLANNER,
                    action=AuditAction.TASK_PUBLISHED,
                    payload={
                        "task_id": task.task_id,
                        "pillar": task.pillar.value,
                        "description": task.description,
                    },
                    correlation_id=correlation_id,
                )

                logger.info(
                    "Task published",
                    extra={
                        "session_id": session_id,
                        "task_id": task.task_id,
                        "pillar": task.pillar,
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to publish task",
                    extra={
                        "session_id": session_id,
                        "task_id": task.task_id,
                        "pillar": task.pillar,
                    },
                )
                self._audit.log(
                    session_id=session_id,
                    user_id=user_id,
                    agent_type=AgentType.PLANNER,
                    action=AuditAction.TASK_FAILED,
                    payload={
                        "task_id": task.task_id,
                        "error": "Service Bus publish failed",
                    },
                    correlation_id=correlation_id,
                )

        self._audit.log(
            session_id=session_id,
            user_id=user_id,
            agent_type=AgentType.PLANNER,
            action=AuditAction.TASK_GRAPH_GENERATED,
            payload={
                "total_tasks": len(tasks),
                "published_tasks": published_count,
                "pillars": list({t.pillar.value for t in tasks}),
            },
            correlation_id=correlation_id,
        )

        logger.info(
            "Task graph published",
            extra={
                "session_id": session_id,
                "total": len(tasks),
                "published": published_count,
            },
        )

        return session
