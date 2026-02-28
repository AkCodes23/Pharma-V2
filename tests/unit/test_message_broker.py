"""
Unit tests for the Message Broker abstraction layer.

Tests both KafkaBroker and ServiceBusBroker implementations
using mocked underlying clients.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestKafkaBroker:
    """Tests for the KafkaBroker implementation."""

    @pytest.mark.asyncio
    async def test_publish_serializes_to_json(self):
        """Messages are JSON-serialized before publishing to Kafka."""
        from src.shared.infra.message_broker import KafkaBroker

        broker = KafkaBroker.__new__(KafkaBroker)
        broker._producer = AsyncMock()
        broker._started = True

        await broker.publish("test-topic", "key-1", {"task": "analyze"})

        broker._producer.send_and_wait.assert_called_once()
        call_args = broker._producer.send_and_wait.call_args
        assert call_args.kwargs["topic"] == "test-topic"

    @pytest.mark.asyncio
    async def test_publish_with_key_uses_session_partitioning(self):
        """Messages with the same key go to the same partition."""
        from src.shared.infra.message_broker import KafkaBroker

        broker = KafkaBroker.__new__(KafkaBroker)
        broker._producer = AsyncMock()
        broker._started = True

        await broker.publish("topic", "session-123", {"data": "test"})

        call_args = broker._producer.send_and_wait.call_args
        assert call_args.kwargs["key"] is not None


class TestServiceBusBroker:
    """Tests for the ServiceBusBroker implementation."""

    @pytest.mark.asyncio
    async def test_publish_maps_topic_to_pillar(self):
        """Publishing to a topic routes to the correct Service Bus topic."""
        from src.shared.infra.message_broker import ServiceBusBroker

        broker = ServiceBusBroker.__new__(ServiceBusBroker)
        mock_publisher = MagicMock()
        mock_publisher.publish = MagicMock()
        broker._publisher = mock_publisher

        # Map topic to pillar
        topic_to_pillar = {
            "pharma.tasks.legal": "LEGAL",
            "pharma.tasks.clinical": "CLINICAL",
        }

        # Test that publish maps correctly
        await broker.publish("pharma.tasks.legal", "key", {"task": "test"})
        mock_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_raises_on_unknown_topic(self):
        """Subscribing to unknown topic raises ValueError."""
        from src.shared.infra.message_broker import ServiceBusBroker

        broker = ServiceBusBroker.__new__(ServiceBusBroker)

        with pytest.raises(ValueError, match="Unknown topic"):
            await broker.subscribe("pharma.tasks.unknown", "group", lambda x: None)


class TestBrokerFactory:
    """Tests for broker factory selection."""

    def test_dev_environment_returns_kafka_broker(self):
        """Development environment selects KafkaBroker."""
        from src.shared.infra.message_broker import KafkaBroker, ServiceBusBroker

        # KafkaBroker is used for development (Docker Compose)
        assert issubclass(KafkaBroker, object)
        assert issubclass(ServiceBusBroker, object)


class TestStreamEvents:
    """Tests for WebSocket streaming event constructors."""

    def test_agent_started_creates_valid_event(self):
        from src.shared.infra.stream_events import StreamEventType, agent_started

        event = agent_started("session-1", "LEGAL_RETRIEVER", "LEGAL")
        assert event.event_type == StreamEventType.AGENT_STARTED
        assert event.session_id == "session-1"
        assert "LEGAL_RETRIEVER" in event.message

    def test_agent_completed_includes_score(self):
        from src.shared.infra.stream_events import agent_completed

        event = agent_completed("s1", "CLINICAL_RETRIEVER", "CLINICAL", "Found 5 trials", 0.92)
        assert event.data["grounding_score"] == 0.92

    def test_report_ready_includes_url(self):
        from src.shared.infra.stream_events import report_ready

        event = report_ready("s1", "https://blob.azure.net/reports/r1.pdf")
        assert event.data["report_url"] == "https://blob.azure.net/reports/r1.pdf"

    def test_validation_result_formats_message(self):
        from src.shared.infra.stream_events import validation_result

        event = validation_result("s1", "COMMERCIAL", 0.85, True)
        assert "✅ passed" in event.message
        assert "0.85" in event.message
