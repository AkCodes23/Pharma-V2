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
import concurrent.futures
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from src.demo.fixture_loader import get_fixture_loader
from src.shared.bootstrap.providers import create_task_consumer
from src.shared.config import get_settings
from src.shared.infra.audit import AuditService
from src.shared.models.enums import AgentType, AuditAction, PillarType, TaskStatus
from src.shared.models.schemas import AgentResult, Citation, ServiceBusMessage, TaskNode
from src.shared.ports.session_store import SessionStore

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
        cosmos: SessionStore,
        audit: AuditService,
        subscription_name: str = "default",
    ) -> None:
        self._cosmos = cosmos
        self._audit = audit
        self._consumer = create_task_consumer(self.pillar, subscription_name)
        self._settings = get_settings()
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            cooldown_seconds=60.0,
            agent_name=self.agent_type.value,
        )
        # Lazy-loaded RAG retriever (import deferred to avoid startup cost)
        self._rag_retriever = None
        # Carries RAG context from _augment_with_rag() to execute_tools()
        self._rag_context: str = ""
        # Reuse a single worker thread for timeout-controlled execution.
        self._tool_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"{self.agent_type.value.lower()}-tools",
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
        future: concurrent.futures.Future[tuple[dict[str, Any], list[Citation]]] = (
            self._tool_executor.submit(self.execute_tools, task)
        )
        try:
            return future.result(timeout=self.EXECUTION_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise ExecutionTimeoutError(
                f"{self.agent_type.value} tool execution exceeded "
                f"{self.EXECUTION_TIMEOUT_SECONDS}s timeout"
            ) from exc

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
            # 1a. RAG augmentation — inject prior knowledge BEFORE tool execution
            self._rag_context = self._augment_with_rag(task, session_id)

            # 2. Execute deterministic tools (with timeout)
            if self._settings.demo_offline:
                findings, citations = self._load_offline_fixture(task)
            else:
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

    def _augment_with_rag(
        self,
        task: TaskNode,
        session_id: str,
    ) -> str:
        """
        Retrieve prior RAG knowledge for this drug+pillar BEFORE tool execution.

        Fail-open: any RAG error returns empty string — agent proceeds normally.
        Uses a new asyncio event loop to call async RAG from sync context.

        The returned context string is stored in self._rag_context and is
        available to execute_tools() via self._rag_context.

        Returns:
            Formatted context string (may be empty if no relevant prior knowledge).
        """
        import asyncio as _asyncio

        try:
            if self._settings.demo_offline:
                return ""

            cfg = self._settings.rag
            if not cfg.enable_rag_augmentation:
                return ""

            from src.shared.rag.rag_retriever import RagRetriever

            # Extract drug name from task parameters
            params = getattr(task, "parameters", {}) or {}
            drug_name = params.get("drug_name", "") or getattr(task, "drug_name", "") or ""
            query = getattr(task, "description", "") or drug_name

            if not drug_name or len(drug_name) < cfg.min_drug_name_length:
                return ""

            retriever = RagRetriever()
            ctx = _asyncio.run(
                retriever.retrieve(
                    query=query,
                    pillar=self.pillar.value,
                    drug_name=drug_name,
                    top_k=5,
                )
            )

            if ctx.is_empty:
                logger.debug(
                    "RAG returned no prior knowledge",
                    extra={"pillar": self.pillar.value, "drug": drug_name},
                )
                return ""

            logger.info(
                "RAG context injected",
                extra={
                    "pillar": self.pillar.value,
                    "drug": drug_name,
                    "chunks": ctx.total_retrieved,
                },
            )
            return ctx.formatted_context

        except Exception as e:
            # Fail-open: RAG augmentation is always best-effort
            logger.warning(
                "RAG augmentation failed — proceeding without context",
                extra={"error": str(e), "pillar": self.pillar.value},
            )
            return ""

    def _load_offline_fixture(self, task: TaskNode) -> tuple[dict[str, Any], list[Citation]]:
        """Load deterministic fixture output for this retriever and task."""
        findings, raw_citations = get_fixture_loader().load_retriever_output(self.pillar, task)
        citations = [Citation.model_validate(item) for item in raw_citations]
        return findings, citations

    def start(self) -> None:
        """Start the consumption loop."""
        logger.info("Starting retriever agent", extra={"agent_type": self.agent_type})
        prefetch_count = int(getattr(self._consumer, "PREFETCH_COUNT", 10))
        self._consumer.consume(
            handler=self.handle_message,
            max_messages=prefetch_count,
        )

    def stop(self) -> None:
        """Stop the consumption loop and cleanup."""
        self._consumer.close()
        self._tool_executor.shutdown(wait=False, cancel_futures=True)
        logger.info("Retriever agent stopped", extra={"agent_type": self.agent_type})

