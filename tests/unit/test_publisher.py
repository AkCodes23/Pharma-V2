"""
Unit tests for Planner Agent — TaskPublisher.

Tests session creation in Cosmos DB, Service Bus message routing,
audit trail entries, and partial publish failure handling.

Uses sys.modules mocking to avoid importing azure.cosmos SDK
(which is not installed in the test environment).
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, call, patch

import pytest

# ── Mock heavy Azure SDK imports before importing publisher ──
# Must use direct assignment (not setdefault) because 'azure' may already
# partially exist in sys.modules from azure-servicebus etc.
import types as _types

_azure_cosmos_mock = MagicMock()
_azure_cosmos_exceptions_mock = MagicMock()

if "azure.cosmos" not in sys.modules or not hasattr(sys.modules.get("azure.cosmos", None), "ContainerProxy"):
    sys.modules["azure.cosmos"] = _azure_cosmos_mock
    sys.modules["azure.cosmos.exceptions"] = _azure_cosmos_exceptions_mock

from src.agents.planner.publisher import TaskPublisher
from src.shared.models.enums import (
    AgentType,
    AuditAction,
    PillarType,
    SessionStatus,
)
from src.shared.models.schemas import QueryParameters, TaskNode


@pytest.fixture
def mock_cosmos() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_servicebus() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_audit() -> MagicMock:
    return MagicMock()


@pytest.fixture
def publisher(mock_cosmos: MagicMock, mock_servicebus: MagicMock, mock_audit: MagicMock) -> TaskPublisher:
    return TaskPublisher(mock_cosmos, mock_servicebus, mock_audit)


@pytest.fixture
def sample_tasks() -> list[TaskNode]:
    return [
        TaskNode(session_id="s-1", pillar=PillarType.LEGAL, description="Legal check", parameters={}),
        TaskNode(session_id="s-1", pillar=PillarType.CLINICAL, description="Clinical check", parameters={}),
        TaskNode(session_id="s-1", pillar=PillarType.COMMERCIAL, description="Market check", parameters={}),
    ]


@pytest.fixture
def sample_params() -> QueryParameters:
    return QueryParameters(
        drug_name="Pembrolizumab",
        brand_name="Keytruda",
        target_market="US",
        time_horizon="2027",
        therapeutic_area="Oncology",
    )


class TestPublishHappyPath:
    """Tests for successful task publishing."""

    def test_creates_session_in_cosmos(
        self, publisher: TaskPublisher, mock_cosmos: MagicMock,
        sample_tasks: list[TaskNode], sample_params: QueryParameters,
    ) -> None:
        session = publisher.publish(
            query="Analyze Keytruda",
            user_id="user-1",
            parameters=sample_params,
            tasks=sample_tasks,
            session_id="s-1",
        )
        mock_cosmos.create_session.assert_called_once()
        created = mock_cosmos.create_session.call_args[0][0]
        assert created.id == "s-1"
        assert created.user_id == "user-1"
        assert created.status == SessionStatus.PLANNING
        assert len(created.task_graph) == 3

    def test_updates_status_to_retrieving(
        self, publisher: TaskPublisher, mock_cosmos: MagicMock,
        sample_tasks: list[TaskNode], sample_params: QueryParameters,
    ) -> None:
        publisher.publish("q", "u", sample_params, sample_tasks, "s-1")
        mock_cosmos.update_session_status.assert_called_with("s-1", SessionStatus.RETRIEVING)

    def test_publishes_each_task_to_service_bus(
        self, publisher: TaskPublisher, mock_servicebus: MagicMock,
        sample_tasks: list[TaskNode], sample_params: QueryParameters,
    ) -> None:
        publisher.publish("q", "u", sample_params, sample_tasks, "s-1")
        assert mock_servicebus.publish_task.call_count == 3

    def test_returns_session_object(
        self, publisher: TaskPublisher,
        sample_tasks: list[TaskNode], sample_params: QueryParameters,
    ) -> None:
        session = publisher.publish("q", "u", sample_params, sample_tasks, "s-1")
        assert session.id == "s-1"
        assert session.query == "q"


class TestPublishAuditTrail:
    """Tests for audit trail entries during publish."""

    def test_logs_session_created(
        self, publisher: TaskPublisher, mock_audit: MagicMock,
        sample_tasks: list[TaskNode], sample_params: QueryParameters,
    ) -> None:
        publisher.publish("q", "u", sample_params, sample_tasks, "s-1")
        # First audit call should be SESSION_CREATED
        first_call = mock_audit.log.call_args_list[0]
        assert first_call.kwargs.get("action") == AuditAction.SESSION_CREATED

    def test_logs_task_published_per_task(
        self, publisher: TaskPublisher, mock_audit: MagicMock,
        sample_tasks: list[TaskNode], sample_params: QueryParameters,
    ) -> None:
        publisher.publish("q", "u", sample_params, sample_tasks, "s-1")
        published_calls = [
            c for c in mock_audit.log.call_args_list
            if c.kwargs.get("action") == AuditAction.TASK_PUBLISHED
        ]
        assert len(published_calls) == 3

    def test_logs_task_graph_generated(
        self, publisher: TaskPublisher, mock_audit: MagicMock,
        sample_tasks: list[TaskNode], sample_params: QueryParameters,
    ) -> None:
        publisher.publish("q", "u", sample_params, sample_tasks, "s-1")
        last_call = mock_audit.log.call_args_list[-1]
        assert last_call.kwargs.get("action") == AuditAction.TASK_GRAPH_GENERATED


class TestPublishCorrelationID:
    """Tests for correlation ID propagation."""

    def test_correlation_id_in_service_bus_message(
        self, publisher: TaskPublisher, mock_servicebus: MagicMock,
        sample_tasks: list[TaskNode], sample_params: QueryParameters,
    ) -> None:
        publisher.publish("q", "u", sample_params, [sample_tasks[0]], "s-1", correlation_id="trace-abc")
        sb_call = mock_servicebus.publish_task.call_args[0][0]
        assert sb_call.correlation_id == "trace-abc"

    def test_correlation_id_in_audit(
        self, publisher: TaskPublisher, mock_audit: MagicMock,
        sample_tasks: list[TaskNode], sample_params: QueryParameters,
    ) -> None:
        publisher.publish("q", "u", sample_params, [sample_tasks[0]], "s-1", correlation_id="trace-xyz")
        for audit_call in mock_audit.log.call_args_list:
            assert audit_call.kwargs.get("correlation_id") == "trace-xyz"


class TestPublishPartialFailure:
    """Tests for partial publish failure handling."""

    def test_partial_failure_continues_remaining(
        self, publisher: TaskPublisher, mock_servicebus: MagicMock, mock_audit: MagicMock,
        sample_tasks: list[TaskNode], sample_params: QueryParameters,
    ) -> None:
        """When one task fails to publish, remaining tasks should still be published."""
        mock_servicebus.publish_task.side_effect = [
            None,  # first succeeds
            Exception("Service Bus unavailable"),  # second fails
            None,  # third succeeds
        ]
        session = publisher.publish("q", "u", sample_params, sample_tasks, "s-1")
        assert mock_servicebus.publish_task.call_count == 3

        # Should log TASK_FAILED for the failed one
        fail_calls = [
            c for c in mock_audit.log.call_args_list
            if c.kwargs.get("action") == AuditAction.TASK_FAILED
        ]
        assert len(fail_calls) == 1

    def test_task_graph_reports_partial_published(
        self, publisher: TaskPublisher, mock_servicebus: MagicMock, mock_audit: MagicMock,
        sample_tasks: list[TaskNode], sample_params: QueryParameters,
    ) -> None:
        mock_servicebus.publish_task.side_effect = [None, Exception("fail"), None]
        publisher.publish("q", "u", sample_params, sample_tasks, "s-1")

        # TASK_GRAPH_GENERATED should report 2 published out of 3
        graph_call = [
            c for c in mock_audit.log.call_args_list
            if c.kwargs.get("action") == AuditAction.TASK_GRAPH_GENERATED
        ][0]
        payload = graph_call.kwargs["payload"]
        assert payload["total_tasks"] == 3
        assert payload["published_tasks"] == 2
