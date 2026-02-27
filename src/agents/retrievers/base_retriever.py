"""
Pharma Agentic AI — Base Retriever Agent.

Abstract base class for all retriever agents in the swarm.
Provides the common lifecycle: Service Bus consumption → tool
execution → Cosmos DB write → audit logging.

Each concrete retriever only needs to implement `execute_tools()`
with its pillar-specific API tool calls.

Architecture context:
  - Service: Retriever Agent Swarm
  - Responsibility: Deterministic API data retrieval
  - Upstream: Azure Service Bus (task messages)
  - Downstream: Cosmos DB (agent results), Blob Storage (raw responses)
  - Scaling: 0 to 100+ via KEDA based on queue depth
  - Failure: DLQ routing after max retries

Performance optimizations:
  - Circuit breaker: Prevents cascading failures across the swarm
  - Execution timeout: 30s default prevents hung agents
  - Structured metrics: Emit latency, success/failure, and breaker state
"""

from __future__ import annotations

import json
import logging
import time
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from src.shared.infra.audit import AuditService
from src.shared.infra.cosmos_client import CosmosDBClient
from src.shared.infra.servicebus_client import ServiceBusConsumer
from src.shared.models.enums import AgentType, AuditAction, PillarType, TaskStatus
from src.shared.models.schemas import AgentResult, Citation, ServiceBusMessage, TaskNode

logger = logging.getLogger(__name__)

# ── Circuit Breaker ───────────────────────────────────────────


class CircuitState(StrEnum):
    """States for the circuit breaker pattern."""
    CLOSED = "CLOSED"        # Normal operation
    OPEN = "OPEN"            # Rejecting all calls (cooling down)
    HALF_OPEN = "HALF_OPEN"  # Allowing one test call


class CircuitBreaker:
    """
    Circuit breaker for agent tool execution.

    Prevents cascading failures when an external API (e.g., USPTO,
    FDA FAERS) is down. Instead of hammering a failed service,
    the breaker trips OPEN after N consecutive failures and rejects
    calls for a cooldown period.

    State machine:
      CLOSED → (failure_count >= threshold) → OPEN
      OPEN → (cooldown elapsed) → HALF_OPEN
      HALF_OPEN → (success) → CLOSED
      HALF_OPEN → (failure) → OPEN

    Thread-safe via threading.Lock.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        agent_name: str = "unknown",
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._agent_name = agent_name

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state (thread-safe read)."""
        with self._lock:
            self._check_cooldown()
            return self._state

    def _check_cooldown(self) -> None:
        """Transition OPEN → HALF_OPEN if cooldown has elapsed."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "Circuit breaker transitioning to HALF_OPEN",
                    extra={"agent": self._agent_name, "elapsed_s": round(elapsed, 1)},
                )

    def allow_request(self) -> bool:
        """
        Check if the circuit allows a request.

        Returns:
            True if the request should proceed, False if rejected.
        """
        with self._lock:
            self._check_cooldown()
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.HALF_OPEN:
                return True  # Allow one test request
            # OPEN — reject
            logger.warning(
                "Circuit breaker OPEN — rejecting request",
                extra={"agent": self._agent_name, "failure_count": self._failure_count},
            )
            return False

    def record_success(self) -> None:
        """Record a successful execution. Resets the breaker."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info(
                    "Circuit breaker recovered → CLOSED",
                    extra={"agent": self._agent_name},
                )
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed execution. May trip the breaker."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker re-tripped → OPEN (HALF_OPEN test failed)",
                    extra={"agent": self._agent_name},
                )
            elif self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN
                logger.error(
                    "Circuit breaker tripped → OPEN",
                    extra={
                        "agent": self._agent_name,
                        "failure_count": self._failure_count,
                        "cooldown_s": self._cooldown_seconds,
                    },
                )


# ── Execution Timeout ─────────────────────────────────────────


class ExecutionTimeoutError(TimeoutError):
    """Raised when tool execution exceeds the configured timeout."""
    pass


# ── Base Retriever ────────────────────────────────────────────


class BaseRetriever(ABC):
    """
    Abstract base class for retriever agents.

    Subclasses MUST implement:
      - agent_type: The AgentType enum value
      - pillar: The PillarType this retriever handles
      - execute_tools(task): Execute deterministic API calls

    Performance features:
      - Circuit breaker: Auto-trips after 3 consecutive failures
      - Execution timeout: 30s default (configurable)
      - Structured metrics: Logs latency, success, and breaker state
    """

    # Configurable timeout for tool execution (seconds)
    EXECUTION_TIMEOUT_SECONDS: float = 30.0

    def __init__(
        self,
        cosmos: CosmosDBClient,
        audit: AuditService,
        subscription_name: str = "default",
    ) -> None:
        self._cosmos = cosmos
        self._audit = audit
        self._consumer = ServiceBusConsumer(
            pillar=self.pillar,
            subscription_name=subscription_name,
        )
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            cooldown_seconds=60.0,
            agent_name=self.agent_type.value,
        )

    @property
    @abstractmethod
    def agent_type(self) -> AgentType:
        """Return the agent type for this retriever."""
        ...

    @property
    @abstractmethod
    def pillar(self) -> PillarType:
        """Return the pillar type this retriever serves."""
        ...

    @abstractmethod
    def execute_tools(self, task: TaskNode) -> tuple[dict[str, Any], list[Citation]]:
        """
        Execute deterministic API tool calls for the given task.

        This method MUST NOT use LLM parametric memory. It MUST
        only call external APIs and return structured data with
        proper citations.

        Args:
            task: The TaskNode with parameters for data retrieval.

        Returns:
            Tuple of (findings_dict, list[Citation]).

        Raises:
            Exception: On API failures (will trigger retry/DLQ).
        """
        ...

    def _execute_with_timeout(self, task: TaskNode) -> tuple[dict[str, Any], list[Citation]]:
        """
        Execute tools with a configurable timeout.

        Uses a daemon thread to enforce the timeout. If execution
        exceeds EXECUTION_TIMEOUT_SECONDS, raises ExecutionTimeoutError.
        """
        result: tuple[dict[str, Any], list[Citation]] | None = None
        error: Exception | None = None

        def _worker() -> None:
            nonlocal result, error
            try:
                result = self.execute_tools(task)
            except Exception as e:
                error = e

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join(timeout=self.EXECUTION_TIMEOUT_SECONDS)

        if thread.is_alive():
            raise ExecutionTimeoutError(
                f"{self.agent_type.value} tool execution exceeded "
                f"{self.EXECUTION_TIMEOUT_SECONDS}s timeout"
            )
        if error is not None:
            raise error
        if result is None:
            raise RuntimeError("Tool execution returned None unexpectedly")
        return result

    def handle_message(self, message: ServiceBusMessage) -> None:
        """
        Process a single task message from Service Bus.

        Lifecycle:
          0. Check circuit breaker
          1. Update task status to RUNNING
          2. Execute deterministic tools (with timeout)
          3. Write AgentResult to Cosmos DB
          4. Update task status to COMPLETED
          5. Log audit entries
        """
        task = message.task
        session_id = message.session_id

        logger.info(
            "Processing task",
            extra={
                "agent_type": self.agent_type,
                "task_id": task.task_id,
                "session_id": session_id,
                "pillar": task.pillar,
                "circuit_state": self._circuit_breaker.state,
            },
        )

        # 0. Circuit breaker check
        if not self._circuit_breaker.allow_request():
            self._cosmos.update_task_status(
                session_id, task.task_id, TaskStatus.RETRYING,
                error_message=f"Circuit breaker OPEN — {self.agent_type.value} cooling down",
            )
            self._audit.log(
                session_id=session_id,
                user_id="system",
                agent_type=self.agent_type,
                action=AuditAction.TASK_RETRIED,
                payload={
                    "task_id": task.task_id,
                    "reason": "circuit_breaker_open",
                    "circuit_state": self._circuit_breaker.state.value,
                },
                correlation_id=message.correlation_id,
            )
            return

        # 1. Mark task as RUNNING
        self._cosmos.update_task_status(session_id, task.task_id, TaskStatus.RUNNING)
        self._audit.log(
            session_id=session_id,
            user_id="system",
            agent_type=self.agent_type,
            action=AuditAction.TASK_STARTED,
            payload={"task_id": task.task_id, "pillar": task.pillar.value},
            correlation_id=message.correlation_id,
        )

        start_time = time.monotonic()

        try:
            # 2. Execute deterministic tools (with timeout)
            findings, citations = self._execute_with_timeout(task)
            execution_time_ms = int((time.monotonic() - start_time) * 1000)

            # 3. Calculate confidence based on citation coverage
            confidence = min(1.0, len(citations) / max(1, len(findings)))

            # 4. Write AgentResult to Cosmos DB
            result = AgentResult(
                task_id=task.task_id,
                session_id=session_id,
                agent_type=self.agent_type,
                pillar=self.pillar,
                findings=findings,
                citations=citations,
                confidence=confidence,
                execution_time_ms=execution_time_ms,
            )
            self._cosmos.add_agent_result(session_id, result)

            # 5. Mark task as COMPLETED
            self._cosmos.update_task_status(session_id, task.task_id, TaskStatus.COMPLETED)

            # Record success with circuit breaker
            self._circuit_breaker.record_success()

            self._audit.log(
                session_id=session_id,
                user_id="system",
                agent_type=self.agent_type,
                action=AuditAction.TASK_COMPLETED,
                payload={
                    "task_id": task.task_id,
                    "findings_keys": list(findings.keys()),
                    "citation_count": len(citations),
                    "execution_time_ms": execution_time_ms,
                    "confidence": confidence,
                    "circuit_state": self._circuit_breaker.state.value,
                },
                correlation_id=message.correlation_id,
            )

            logger.info(
                "Task completed",
                extra={
                    "task_id": task.task_id,
                    "execution_time_ms": execution_time_ms,
                    "citation_count": len(citations),
                    "circuit_state": self._circuit_breaker.state.value,
                },
            )

        except ExecutionTimeoutError as e:
            execution_time_ms = int((time.monotonic() - start_time) * 1000)
            self._circuit_breaker.record_failure()
            logger.error(
                "Task execution timed out",
                extra={"task_id": task.task_id, "timeout_s": self.EXECUTION_TIMEOUT_SECONDS},
            )
            self._cosmos.update_task_status(
                session_id, task.task_id, TaskStatus.FAILED, error_message=str(e),
            )
            self._audit.log(
                session_id=session_id,
                user_id="system",
                agent_type=self.agent_type,
                action=AuditAction.TASK_DLQ,
                payload={"task_id": task.task_id, "error": str(e), "execution_time_ms": execution_time_ms},
                correlation_id=message.correlation_id,
            )

        except Exception as e:
            execution_time_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"{type(e).__name__}: {e}"
            self._circuit_breaker.record_failure()

            logger.exception(
                "Task execution failed",
                extra={
                    "task_id": task.task_id,
                    "error": error_msg,
                    "circuit_state": self._circuit_breaker.state.value,
                },
            )

            # Check if retryable
            if task.retry_count < 3:
                self._cosmos.update_task_status(
                    session_id, task.task_id, TaskStatus.RETRYING, error_message=error_msg
                )
                self._audit.log(
                    session_id=session_id,
                    user_id="system",
                    agent_type=self.agent_type,
                    action=AuditAction.TASK_RETRIED,
                    payload={"task_id": task.task_id, "retry_count": task.retry_count + 1},
                    correlation_id=message.correlation_id,
                )
            else:
                self._cosmos.update_task_status(
                    session_id, task.task_id, TaskStatus.DLQ, error_message=error_msg
                )
                self._audit.log(
                    session_id=session_id,
                    user_id="system",
                    agent_type=self.agent_type,
                    action=AuditAction.TASK_DLQ,
                    payload={"task_id": task.task_id, "final_error": error_msg},
                    correlation_id=message.correlation_id,
                )

    def start(self) -> None:
        """Start the consumption loop."""
        logger.info("Starting retriever agent", extra={"agent_type": self.agent_type})
        self._consumer.consume(handler=self.handle_message)

    def stop(self) -> None:
        """Stop the consumption loop and cleanup."""
        self._consumer.close()
        logger.info("Retriever agent stopped", extra={"agent_type": self.agent_type})
