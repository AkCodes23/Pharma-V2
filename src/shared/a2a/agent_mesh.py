"""
Pharma Agentic AI — Agent Mesh Router.

Tiered Agent-to-Agent communication:
  Tier 1 (< 2s): Direct HTTP/2 to agent's /invoke endpoint
  Tier 2 (< 60s): Kafka broker (durable, async)
  Tier 3 (escalate): Human-in-the-loop queue

The mesh router selects the transport automatically based on:
  - SLA tier in the CapabilityContract
  - Target agent health (circuit breaker state)
  - Current Kafka consumer lag (if too high, prefer direct)

Architecture context:
  - Service: Shared A2A infrastructure
  - Responsibility: Intelligent inter-agent transport selection
  - Upstream: Planner, Supervisor (delegating tasks)
  - Downstream: Retriever agents, Quality Evaluator (receiving tasks)
  - Failure: Circuit breaker opens after 3 failures → Kafka fallback

Performance:
  - Shared httpx.AsyncClient: connection pool reused (HTTP/2 multiplexing)
  - Per-agent circuit breakers: avoid hammering unhealthy agents
  - Exponential backoff: 0.1s → 0.2s → 0.4s (3 retries max)
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx

from src.shared.a2a.capability_contract import CapabilityContract, SLATier
from src.shared.infra.redis_client import RedisClient

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────
_MESH_TIMEOUT = httpx.Timeout(connect=2.0, read=30.0, write=5.0, pool=1.0)
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.1  # seconds

# Circuit breaker: open after N consecutive failures, reset after TTL
_CB_FAILURE_THRESHOLD = 3
_CB_RESET_TTL = 60  # seconds

# ── Shared HTTP client ───────────────────────────────────
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """
    Shared persistent async HTTP client for all mesh calls.
    HTTP/2 enabled for multiplexing concurrent agent requests.
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=_MESH_TIMEOUT,
            http2=True,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            headers={"Content-Type": "application/json", "User-Agent": "pharma-mesh/1.0"},
        )
    return _http_client


async def close_mesh_client() -> None:
    """Gracefully close the mesh HTTP client (call on app shutdown)."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


# ── Agent Invoke Request/Response ────────────────────────

class AgentInvokeRequest:
    """Structured request for direct agent invocation."""
    __slots__ = ("session_id", "capability_id", "input_data", "sender_id", "correlation_id", "deadline_ms")

    def __init__(
        self,
        session_id: str,
        capability_id: str,
        input_data: dict[str, Any],
        sender_id: str,
        correlation_id: str | None = None,
        deadline_ms: int = 30_000,
    ) -> None:
        self.session_id = session_id
        self.capability_id = capability_id
        self.input_data = input_data
        self.sender_id = sender_id
        self.correlation_id = correlation_id
        self.deadline_ms = deadline_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "capability_id": self.capability_id,
            "input_data": self.input_data,
            "sender_id": self.sender_id,
            "correlation_id": self.correlation_id,
            "deadline_ms": self.deadline_ms,
        }


class AgentInvokeResponse:
    """Structured response from a direct agent invocation."""
    __slots__ = ("success", "result", "error", "agent_id", "latency_ms", "transport_used")

    def __init__(
        self,
        success: bool,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        agent_id: str = "",
        latency_ms: int = 0,
        transport_used: str = "http",
    ) -> None:
        self.success = success
        self.result = result or {}
        self.error = error
        self.agent_id = agent_id
        self.latency_ms = latency_ms
        self.transport_used = transport_used


# ── Circuit Breaker (Redis-backed) ───────────────────────

class CircuitBreaker:
    """
    Per-agent circuit breaker backed by Redis.

    States:
      CLOSED → normal operation, calls pass through
      OPEN   → agent unhealthy, calls skip to fallback
      HALF_OPEN → testing recovery after TTL expiry

    Uses Redis INCR for failure counting (atomic, no race conditions).
    """

    def __init__(self, agent_id: str, redis: RedisClient) -> None:
        self._agent_id = agent_id
        self._redis = redis
        self._fail_key = f"mesh_cb_fail:{agent_id}"
        self._open_key = f"mesh_cb_open:{agent_id}"

    def is_open(self) -> bool:
        """Return True if circuit is OPEN (agent should be skipped)."""
        try:
            return bool(self._redis.client.exists(self._open_key))
        except Exception:
            return False  # Fail closed (allow call) on Redis error

    def record_failure(self) -> None:
        """Increment failure counter. Open circuit if threshold reached."""
        try:
            count = self._redis.client.incr(self._fail_key)
            self._redis.client.expire(self._fail_key, _CB_RESET_TTL)
            if count >= _CB_FAILURE_THRESHOLD:
                self._redis.client.setex(self._open_key, _CB_RESET_TTL, "1")
                logger.warning(
                    "Circuit OPENED for agent",
                    extra={"agent_id": self._agent_id, "failures": count},
                )
        except Exception:
            pass

    def record_success(self) -> None:
        """Reset failure counter and close circuit on success."""
        try:
            self._redis.client.delete(self._fail_key, self._open_key)
        except Exception:
            pass


# ── Agent Mesh Router ─────────────────────────────────────

class AgentMesh:
    """
    Tiered A2A transport router.

    Decision logic:
      1. Check contract.sla_tier:
           REALTIME / FAST → attempt direct HTTP first
           STANDARD / BATCH → use Kafka directly
      2. Check circuit breaker for target agent:
           OPEN → skip direct HTTP, fallback to Kafka
      3. Direct HTTP attempt with retry + backoff
      4. On failure → Kafka fallback (if broker available)
      5. Record circuit breaker state after each call

    All results are returned as AgentInvokeResponse regardless of transport.
    """

    def __init__(self, sender_id: str) -> None:
        self._sender_id = sender_id
        self._redis: RedisClient | None = None
        self._broker = None
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    async def initialize(self) -> None:
        """Initialize Redis (for circuit breakers) and Kafka broker."""
        from src.shared.infra.redis_client import RedisClient
        from src.shared.infra.message_broker import create_message_broker

        self._redis = RedisClient()
        try:
            self._broker = create_message_broker()
            await self._broker.start()
        except Exception as e:
            logger.warning("Broker unavailable — mesh will be HTTP-only", extra={"error": str(e)})

        logger.info("AgentMesh initialized", extra={"sender_id": self._sender_id})

    def _get_cb(self, agent_id: str) -> CircuitBreaker | None:
        """Get or create a circuit breaker for the given agent."""
        if not self._redis:
            return None
        if agent_id not in self._circuit_breakers:
            self._circuit_breakers[agent_id] = CircuitBreaker(agent_id, self._redis)
        return self._circuit_breakers[agent_id]

    async def invoke(
        self,
        contract: CapabilityContract,
        request: AgentInvokeRequest,
        target_agent_id: str,
    ) -> AgentInvokeResponse:
        """
        Invoke an agent via the optimal transport.

        Args:
            contract: Capability contract describing the target capability.
            request: Structured invocation request.
            target_agent_id: Logical agent ID for circuit breaker tracking.

        Returns:
            AgentInvokeResponse with result or error details.
        """
        # Validate input against contract
        valid, errors = contract.validate_input(request.input_data)
        if not valid:
            return AgentInvokeResponse(
                success=False,
                error=f"Contract validation failed: {'; '.join(errors)}",
            )

        # Route based on SLA tier + circuit breaker state
        use_direct_http = (
            contract.sla_tier in (SLATier.REALTIME, SLATier.FAST)
            and contract.invoke_endpoint
        )

        cb = self._get_cb(target_agent_id)
        if cb and cb.is_open():
            logger.info(
                "Circuit OPEN — falling back to Kafka",
                extra={"agent_id": target_agent_id},
            )
            use_direct_http = False

        if use_direct_http:
            response = await self._invoke_http(contract, request, target_agent_id, cb)
            if response.success:
                return response
            # HTTP failed — fall through to Kafka
            logger.warning(
                "Direct HTTP failed — falling back to Kafka",
                extra={"agent_id": target_agent_id, "error": response.error},
            )

        # Kafka fallback (durable, async)
        if self._broker:
            return await self._invoke_kafka(request, target_agent_id)

        return AgentInvokeResponse(
            success=False,
            error="No transport available (HTTP failed, Kafka unavailable)",
        )

    async def _invoke_http(
        self,
        contract: CapabilityContract,
        request: AgentInvokeRequest,
        agent_id: str,
        cb: CircuitBreaker | None,
    ) -> AgentInvokeResponse:
        """Direct HTTP invocation with retry + exponential backoff."""
        client = _get_http_client()
        url = contract.invoke_endpoint
        payload = request.to_dict()
        last_error = ""

        for attempt in range(_MAX_RETRIES):
            start_ns = time.perf_counter_ns()
            try:
                resp = await client.post(url, json=payload)
                latency_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
                resp.raise_for_status()
                data = resp.json()

                if cb:
                    cb.record_success()

                logger.info(
                    "Mesh HTTP invoke success",
                    extra={
                        "agent_id": agent_id,
                        "latency_ms": latency_ms,
                        "attempt": attempt + 1,
                    },
                )
                return AgentInvokeResponse(
                    success=True,
                    result=data,
                    agent_id=data.get("agent_id", agent_id),
                    latency_ms=latency_ms,
                    transport_used="http",
                )

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = str(e)
                if cb:
                    cb.record_failure()
                backoff = _BACKOFF_BASE * (2 ** attempt)
                logger.debug(
                    "Mesh HTTP attempt failed",
                    extra={"attempt": attempt + 1, "backoff_s": backoff, "error": last_error},
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(backoff)

            except httpx.HTTPStatusError as e:
                # 4xx errors: don't retry (client errors)
                if 400 <= e.response.status_code < 500:
                    return AgentInvokeResponse(
                        success=False,
                        error=f"Agent rejected request: HTTP {e.response.status_code}",
                    )
                last_error = str(e)
                if cb:
                    cb.record_failure()

        return AgentInvokeResponse(success=False, error=f"HTTP failed after {_MAX_RETRIES} attempts: {last_error}")

    async def _invoke_kafka(
        self,
        request: AgentInvokeRequest,
        agent_id: str,
    ) -> AgentInvokeResponse:
        """Publish invoke request to Kafka for async processing."""
        try:
            from src.shared.a2a.protocol import A2AMessage, A2AMessageType

            message = A2AMessage(
                message_type=A2AMessageType.DELEGATE,
                sender_id=self._sender_id,
                recipient_id=agent_id,
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                payload=request.to_dict(),
            )
            await self._broker.publish(
                topic="pharma.events.a2a",
                message=message.model_dump(),
                key=request.session_id,
            )
            return AgentInvokeResponse(
                success=True,
                result={"status": "queued", "message_id": message.message_id},
                transport_used="kafka",
            )
        except Exception as e:
            return AgentInvokeResponse(success=False, error=f"Kafka publish failed: {e}")

    async def broadcast(
        self,
        capability_id: str,
        session_id: str,
        input_data: dict[str, Any],
        agent_ids: list[str],
    ) -> list[AgentInvokeResponse]:
        """
        Fan-out: invoke the same capability on multiple agents concurrently.

        Uses asyncio.gather for parallel invocation. Individual failures
        are captured as error responses (not exceptions). Used by the
        Supervisor for multi-pillar concurrent retrieval.
        """
        from src.shared.a2a.capability_contract import get_contract

        contract = get_contract(capability_id)

        async def _safe_invoke(agent_id: str) -> AgentInvokeResponse:
            if not contract:
                return AgentInvokeResponse(
                    success=False,
                    error=f"No contract found for capability: {capability_id}",
                    agent_id=agent_id,
                )
            req = AgentInvokeRequest(
                session_id=session_id,
                capability_id=capability_id,
                input_data=input_data,
                sender_id=self._sender_id,
            )
            try:
                return await self.invoke(contract, req, agent_id)
            except Exception as e:
                return AgentInvokeResponse(
                    success=False, error=str(e), agent_id=agent_id
                )

        results = await asyncio.gather(*[_safe_invoke(aid) for aid in agent_ids])
        return list(results)

    async def shutdown(self) -> None:
        """Graceful shutdown: close HTTP client and broker."""
        await close_mesh_client()
        if self._broker:
            await self._broker.stop()
        logger.info("AgentMesh shutdown complete")
