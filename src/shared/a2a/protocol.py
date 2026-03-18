"""
Pharma Agentic AI — A2A Protocol.

Defines the Agent-to-Agent communication protocol for inter-agent
task delegation, result reporting, and escalation.

Architecture context:
  - Service: Shared A2A protocol
  - Responsibility: Message format and routing between agents
  - Pattern: Discover → Delegate → Report → Escalate
  - Transport: Kafka events (dev) / Service Bus (prod)

Protocol messages:
  1. DISCOVER: Query registry for agents with a capability
  2. DELEGATE: Forward a sub-task to a discovered agent
  3. REPORT: Return result from delegated task
  4. ESCALATE: Route to human-in-the-loop (low confidence)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class A2AMessageType(str, Enum):
    """A2A protocol message types."""
    DISCOVER = "discover"
    DELEGATE = "delegate"
    REPORT = "report"
    ESCALATE = "escalate"
    HEARTBEAT = "heartbeat"
    ACK = "ack"
    # Mesh extensions
    NEGOTIATE = "negotiate"  # Capability contract exchange before delegation
    INVOKE = "invoke"        # Direct synchronous invocation (bypasses Kafka)


class A2AMessage(BaseModel):
    """
    A2A protocol message envelope.

    Every inter-agent communication uses this format.
    The payload varies by message_type.
    """
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    message_type: A2AMessageType
    sender_id: str
    recipient_id: str | None = None  # None for broadcast (DISCOVER)
    session_id: str
    correlation_id: str | None = None  # Links request → response
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = 300  # Message expires after 5 min


class NegotiatePayload(BaseModel):
    """
    Payload for NEGOTIATE messages.

    Sender requests a capability contract from the target agent.
    Target responds with its CapabilityContract (as JSON Schema).
    Allows the Planner to validate inputs BEFORE delegation.
    """
    capability_id: str
    requested_sla_tier: str = "standard"
    input_preview: dict[str, Any] = Field(default_factory=dict)
    accept_partial: bool = True


class InvokePayload(BaseModel):
    """
    Payload for INVOKE messages (direct synchronous execution).

    Used by the AgentMesh for direct HTTP invocation.
    Unlike DELEGATE (fire-and-forget), INVOKE expects a synchronous
    response within deadline_ms at the HTTP level.
    """
    capability_id: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    deadline_ms: int = 30_000
    sender_endpoint: str = ""  # For callback if HTTP invoke times out


class DelegatePayload(BaseModel):
    """Payload for DELEGATE messages."""
    task_description: str
    required_capability: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    priority: int = 5  # 1 (urgent) to 10 (background)
    deadline_seconds: int = 120


class ReportPayload(BaseModel):
    """Payload for REPORT messages (task result)."""
    task_id: str
    status: str  # completed, failed, partial
    result: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    execution_time_ms: int = 0
    citations: list[dict[str, Any]] = Field(default_factory=list)


class EscalatePayload(BaseModel):
    """Payload for ESCALATE messages (human-in-the-loop)."""
    reason: str
    confidence: float
    threshold: float
    context: dict[str, Any] = Field(default_factory=dict)
    suggested_action: str = ""


class A2AProtocol:
    """
    A2A protocol handler for sending and receiving inter-agent messages.

    Uses the MessageBroker abstraction for transport, so it works
    with both Kafka (dev) and Service Bus (prod).
    """

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self._broker = None

    async def initialize(self) -> None:
        """Initialize the message broker for A2A communication."""
        from src.shared.infra.message_broker import create_message_broker
        self._broker = create_message_broker()
        await self._broker.start()
        logger.info("A2A protocol initialized", extra={"agent_id": self._agent_id})

    async def delegate_task(
        self,
        session_id: str,
        recipient_id: str,
        task_description: str,
        required_capability: str,
        input_data: dict[str, Any],
        priority: int = 5,
    ) -> str:
        """
        Delegate a sub-task to another agent.

        Args:
            session_id: Session context.
            recipient_id: Target agent ID.
            task_description: What the agent should do.
            required_capability: Required agent capability.
            input_data: Input for the delegated task.
            priority: Task priority (1=urgent, 10=background).

        Returns:
            Message ID for tracking.
        """
        payload = DelegatePayload(
            task_description=task_description,
            required_capability=required_capability,
            input_data=input_data,
            priority=priority,
        )

        message = A2AMessage(
            message_type=A2AMessageType.DELEGATE,
            sender_id=self._agent_id,
            recipient_id=recipient_id,
            session_id=session_id,
            payload=payload.model_dump(),
        )

        if self._broker:
            await self._broker.publish(
                topic="pharma.events.a2a",
                key=session_id,
                message=message.model_dump(),
            )

        logger.info(
            "Task delegated",
            extra={
                "sender": self._agent_id,
                "recipient": recipient_id,
                "capability": required_capability,
            },
        )

        return message.message_id

    async def report_result(
        self,
        session_id: str,
        recipient_id: str,
        task_id: str,
        result: dict[str, Any],
        confidence: float,
        execution_time_ms: int,
        correlation_id: str | None = None,
    ) -> None:
        """Report the result of a delegated task back to the sender."""
        payload = ReportPayload(
            task_id=task_id,
            status="completed",
            result=result,
            confidence=confidence,
            execution_time_ms=execution_time_ms,
        )

        message = A2AMessage(
            message_type=A2AMessageType.REPORT,
            sender_id=self._agent_id,
            recipient_id=recipient_id,
            session_id=session_id,
            correlation_id=correlation_id,
            payload=payload.model_dump(),
        )

        if self._broker:
            await self._broker.publish(
                topic="pharma.events.a2a",
                key=session_id,
                message=message.model_dump(),
            )

    async def escalate(
        self,
        session_id: str,
        reason: str,
        confidence: float,
        threshold: float,
        context: dict[str, Any],
    ) -> None:
        """
        Escalate to human-in-the-loop when agent confidence is below threshold.

        This halts automated processing and routes to a human reviewer.
        """
        payload = EscalatePayload(
            reason=reason,
            confidence=confidence,
            threshold=threshold,
            context=context,
        )

        message = A2AMessage(
            message_type=A2AMessageType.ESCALATE,
            sender_id=self._agent_id,
            session_id=session_id,
            payload=payload.model_dump(),
        )

        if self._broker:
            await self._broker.publish(
                topic="pharma.events.a2a",
                key=session_id,
                message=message.model_dump(),
            )

        logger.warning(
            "Task escalated to human",
            extra={
                "session_id": session_id,
                "reason": reason,
                "confidence": confidence,
            },
        )

    async def shutdown(self) -> None:
        """Shutdown the A2A protocol handler."""
        if self._broker:
            await self._broker.stop()
