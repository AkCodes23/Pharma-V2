"""
Unit tests for the Agent Mesh Router.

Tests the tiered transport selection, circuit breaker logic,
and fan-out broadcasting. Uses respx for HTTP mocking and
fakeredis for Redis circuit breaker state.
"""

from __future__ import annotations

import pytest
import respx
import httpx
import fakeredis

from src.shared.a2a.agent_mesh import AgentMesh, CircuitBreaker, AgentInvokeRequest, AgentInvokeResponse
from src.shared.a2a.capability_contract import (
    CapabilityContract, CapabilityCategory, SLATier, ContractSchema, FieldSchema, PHARMA_CONTRACTS
)
from src.shared.infra.redis_client import RedisClient


# ── Fixtures ─────────────────────────────────────────────

@pytest.fixture
def fake_redis_client(monkeypatch):
    """Inject fakeredis into RedisClient for isolated tests."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("src.shared.infra.redis_client.redis.Redis", lambda **kwargs: fake)
    monkeypatch.setattr("src.shared.infra.redis_client.redis.ConnectionPool.from_url", lambda **kwargs: None)
    return fake


@pytest.fixture
def sample_contract() -> CapabilityContract:
    """A minimal capability contract for testing."""
    return CapabilityContract(
        capability_id="test_retrieval",
        capability_name="Test Retrieval",
        category=CapabilityCategory.RETRIEVAL,
        sla_tier=SLATier.FAST,
        invoke_endpoint="http://test-agent:8999/invoke",
        input_schema=ContractSchema(
            fields=[
                FieldSchema(name="drug_name", type="str", required=True),
                FieldSchema(name="session_id", type="str", required=True),
            ]
        ),
        output_schema=ContractSchema(
            fields=[FieldSchema(name="findings", type="dict", required=True)]
        ),
    )


@pytest.fixture
def invoke_request() -> AgentInvokeRequest:
    return AgentInvokeRequest(
        session_id="00000000-0000-0000-0000-000000000001",
        capability_id="test_retrieval",
        input_data={"drug_name": "Semaglutide", "session_id": "00000000-0000-0000-0000-000000000001"},
        sender_id="planner",
    )


# ── Capability Contract Tests ─────────────────────────────

class TestCapabilityContract:

    def test_validate_input_passes(self, sample_contract):
        valid, errors = sample_contract.validate_input({
            "drug_name": "Semaglutide",
            "session_id": "abc-123",
        })
        assert valid is True
        assert errors == []

    def test_validate_input_missing_required(self, sample_contract):
        valid, errors = sample_contract.validate_input({"drug_name": "Ozempic"})
        assert valid is False
        assert any("session_id" in e for e in errors)

    def test_to_json_schema(self, sample_contract):
        schema = sample_contract.input_schema.to_json_schema()
        assert schema["type"] == "object"
        assert "drug_name" in schema["properties"]
        assert "drug_name" in schema["required"]

    def test_capability_id_no_spaces(self):
        with pytest.raises(ValueError, match="must not contain spaces"):
            CapabilityContract(
                capability_id="bad id with spaces",
                capability_name="Bad",
                category=CapabilityCategory.RETRIEVAL,
            )

    def test_pharma_contracts_registered(self):
        assert "fda_drug_retrieval" in PHARMA_CONTRACTS
        assert "clinical_trials_retrieval" in PHARMA_CONTRACTS
        assert len(PHARMA_CONTRACTS) >= 5

    def test_roundtrip_serialization(self, sample_contract):
        d = sample_contract.to_dict()
        restored = CapabilityContract.from_dict(d)
        assert restored.capability_id == sample_contract.capability_id
        assert restored.sla_tier == sample_contract.sla_tier


# ── Circuit Breaker Tests ─────────────────────────────────

class TestCircuitBreaker:

    def test_closed_by_default(self, fake_redis_client):
        redis_client = RedisClient.__new__(RedisClient)
        redis_client._client = fake_redis_client
        cb = CircuitBreaker("test_agent", redis_client)
        assert cb.is_open() is False

    def test_opens_after_threshold(self, fake_redis_client):
        redis_client = RedisClient.__new__(RedisClient)
        redis_client._client = fake_redis_client
        cb = CircuitBreaker("test_agent2", redis_client)
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open() is True

    def test_resets_on_success(self, fake_redis_client):
        redis_client = RedisClient.__new__(RedisClient)
        redis_client._client = fake_redis_client
        cb = CircuitBreaker("test_agent3", redis_client)
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open() is True
        cb.record_success()
        assert cb.is_open() is False


# ── Agent Mesh HTTP Tests ─────────────────────────────────

class TestAgentMeshHTTP:

    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_direct_http(self, sample_contract, invoke_request):
        """Happy path: direct HTTP invoke returns 200."""
        respx.post("http://test-agent:8999/invoke").mock(
            return_value=httpx.Response(200, json={
                "success": True,
                "agent_id": "test-agent",
                "result": {"findings": {"drug": "Semaglutide"}},
            })
        )

        mesh = AgentMesh(sender_id="planner")
        response = await mesh._invoke_http(
            contract=sample_contract,
            request=invoke_request,
            agent_id="test-agent",
            cb=None,
        )

        assert response.success is True
        assert response.transport_used == "http"
        assert response.latency_ms >= 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_retry_on_timeout(self, sample_contract, invoke_request):
        """Three consecutive timeouts → fail with error message."""
        respx.post("http://test-agent:8999/invoke").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        mesh = AgentMesh(sender_id="planner")
        response = await mesh._invoke_http(
            contract=sample_contract,
            request=invoke_request,
            agent_id="test-agent",
            cb=None,
        )

        assert response.success is False
        assert "failed after" in response.error.lower()

    @pytest.mark.asyncio
    async def test_contract_validation_before_call(self, sample_contract):
        """Input validation failure short-circuits before any HTTP call."""
        mesh = AgentMesh(sender_id="planner")
        bad_request = AgentInvokeRequest(
            session_id="00000000-0000-0000-0000-000000000001",
            capability_id="test_retrieval",
            input_data={"drug_name": "only-one-field"},  # missing session_id
            sender_id="planner",
        )
        response = await mesh.invoke(
            contract=sample_contract,
            request=bad_request,
            target_agent_id="test-agent",
        )
        assert response.success is False
        assert "validation" in response.error.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_fan_out_broadcast(self, sample_contract, invoke_request):
        """Fan-out: both agents called concurrently, results collected."""
        respx.post("http://test-agent:8999/invoke").mock(
            return_value=httpx.Response(200, json={"success": True, "result": {}})
        )

        mesh = AgentMesh(sender_id="supervisor")
        # Without real broker, patch _invoke_http directly
        import unittest.mock as mock
        mock_response = AgentInvokeResponse(success=True, result={"data": 1}, transport_used="http")

        with mock.patch.object(mesh, "_invoke_http", return_value=mock_response):
            with mock.patch.object(mesh, "_broker", None):
                responses = await mesh.broadcast(
                    capability_id="test_retrieval",
                    session_id="test-session",
                    input_data={"drug_name": "Semaglutide", "session_id": "test-session"},
                    agent_ids=["agent-1", "agent-2"],
                )

        assert len(responses) == 2
