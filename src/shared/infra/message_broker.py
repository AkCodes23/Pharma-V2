"""
Pharma Agentic AI — Message Broker Abstraction.

Provides a unified interface for message publishing and consumption,
allowing transparent switching between Azure Service Bus (production)
and Kafka (local development) without changing agent code.

Architecture context:
  - Service: Shared infrastructure
  - Responsibility: Abstract message routing from concrete broker
  - Upstream: Planner Agent (publisher), all agents (event emitters)
  - Downstream: Service Bus (Azure prod) or Kafka (Docker local)
  - Failure: Delegates to underlying broker's retry/DLQ mechanisms

Design pattern: Strategy pattern with factory function.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable
from uuid import uuid4

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class MessageBroker(ABC):
    """
    Abstract message broker interface.

    All agent code should use this interface, not Service Bus or
    Kafka directly. This enables local development with Kafka
    while using Service Bus in Azure production.
    """

    @abstractmethod
    async def publish(self, topic: str, key: str | None, message: dict[str, Any]) -> None:
        """Publish a message to a topic/queue."""
        ...

    @abstractmethod
    async def publish_task(self, pillar: str, message_data: dict[str, Any], session_id: str) -> None:
        """Publish a task message to a pillar-specific topic."""
        ...

    @abstractmethod
    async def subscribe(self, topic: str, group_id: str, handler: Callable[[dict[str, Any]], None]) -> None:
        """Subscribe to a topic and process messages via handler."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Initialize underlying connections."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shutdown connections."""
        ...


class KafkaBroker(MessageBroker):
    """Kafka implementation of the MessageBroker interface."""

    def __init__(self) -> None:
        from src.shared.infra.kafka_client import KafkaEventConsumer, KafkaEventProducer
        self._producer = KafkaEventProducer()
        self._consumers: list[KafkaEventConsumer] = []

    async def start(self) -> None:
        await self._producer.start()

    async def publish(self, topic: str, key: str | None, message: dict[str, Any]) -> None:
        payload = message if isinstance(message, dict) else {"data": message}

        send_and_wait = getattr(self._producer, "send_and_wait", None)
        if callable(send_and_wait):
            await send_and_wait(topic=topic, value=payload, key=key)
            return

        publish_event = getattr(self._producer, "publish_event", None)
        if callable(publish_event):
            await publish_event(
                topic=topic,
                event_type=payload.get("event_type", "unknown"),
                data=payload,
                key=key,
            )
            return

        raise RuntimeError("Kafka producer not initialized")

    async def publish_task(self, pillar: str, message_data: dict[str, Any], session_id: str) -> None:
        await self._producer.publish_task(pillar, message_data, session_id)

    async def subscribe(self, topic: str, group_id: str, handler: Callable[[dict[str, Any]], None]) -> None:
        from src.shared.infra.kafka_client import KafkaEventConsumer
        consumer = KafkaEventConsumer(topic=topic, group_id=group_id)
        self._consumers.append(consumer)
        await consumer.start(handler)

    async def stop(self) -> None:
        await self._producer.stop()
        for consumer in self._consumers:
            await consumer.stop()
        self._consumers.clear()


class ServiceBusBroker(MessageBroker):
    """
    Azure Service Bus implementation of the MessageBroker interface.

    Wraps the existing ServiceBusPublisher/Consumer for production use.
    """

    def __init__(self) -> None:
        from src.shared.infra.servicebus_client import ServiceBusPublisher
        self._publisher = ServiceBusPublisher()

    async def start(self) -> None:
        # ServiceBusPublisher initializes on construction
        pass

    async def publish(self, topic: str, key: str | None, message: dict[str, Any]) -> None:
        import asyncio
        import json
        from uuid import uuid4

        from azure.servicebus import ServiceBusMessage as AzureMessage
        from pydantic import ValidationError
        from src.shared.models.schemas import ServiceBusMessage

        payload = message if isinstance(message, dict) else {"data": message}

        try:
            sb_message = ServiceBusMessage.model_validate(payload)
            self._publisher.publish_task(sb_message)
            return
        except ValidationError:
            logger.debug(
                "ServiceBusBroker publish payload not a ServiceBusMessage; using raw envelope",
                extra={"topic": topic},
            )

        publish_fn = getattr(self._publisher, "publish", None)
        if callable(publish_fn):
            publish_fn(topic, key, payload)
            return

        try:
            sender = self._publisher._client.get_topic_sender(topic_name=topic)  # type: ignore[attr-defined]
            azure_msg = AzureMessage(body=json.dumps(payload, default=str))
            azure_msg.message_id = key or payload.get("message_id") or str(uuid4())
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, sender.send_messages, azure_msg)
        except Exception:
            logger.warning(
                "ServiceBusBroker publish fallback failed",
                extra={"topic": topic},
                exc_info=True,
            )

    async def publish_task(self, pillar: str, message_data: dict[str, Any], session_id: str) -> None:
        from src.shared.models.schemas import ServiceBusMessage
        sb_message = ServiceBusMessage.model_validate(message_data)
        self._publisher.publish_task(sb_message)

    async def subscribe(self, topic: str, group_id: str, handler: Callable[[dict[str, Any]], None]) -> None:
        from src.shared.infra.servicebus_client import ServiceBusConsumer
        from src.shared.models.enums import PillarType
        from src.shared.models.schemas import ServiceBusMessage

        # Source of truth is Service Bus topic naming: "*-tasks".
        # Keep legacy Kafka-style aliases for backward compatibility.
        pillar_map = {
            "legal-tasks": PillarType.LEGAL,
            "clinical-tasks": PillarType.CLINICAL,
            "commercial-tasks": PillarType.COMMERCIAL,
            "social-tasks": PillarType.SOCIAL,
            "knowledge-tasks": PillarType.KNOWLEDGE,
            "news-tasks": PillarType.NEWS,
            "pharma.tasks.legal": PillarType.LEGAL,
            "pharma.tasks.clinical": PillarType.CLINICAL,
            "pharma.tasks.commercial": PillarType.COMMERCIAL,
            "pharma.tasks.social": PillarType.SOCIAL,
            "pharma.tasks.knowledge": PillarType.KNOWLEDGE,
            "pharma.tasks.news": PillarType.NEWS,
        }
        pillar = pillar_map.get(topic)
        if not pillar:
            raise ValueError(f"Unknown topic for Service Bus mapping: {topic}")

        # ServiceBusConsumer.consume expects Callable[[ServiceBusMessage], None]
        # but our abstract interface uses Callable[[dict], None]. Bridge the types:
        def sb_handler(msg: ServiceBusMessage) -> None:
            handler(msg.model_dump())

        consumer = ServiceBusConsumer(pillar=pillar, subscription_name=group_id)
        consumer.consume(handler=sb_handler)

    async def stop(self) -> None:
        self._publisher.close()


def create_message_broker() -> MessageBroker:
    """
    Factory function: returns the appropriate broker based on environment.

    - development/docker → KafkaBroker
    - production/staging → ServiceBusBroker

    This is the ONLY place broker selection happens. All agent code
    calls create_message_broker() and uses the abstract interface.
    """
    settings = get_settings()
    env = settings.app.env.lower()

    if env in ("production", "staging"):
        logger.info("Using ServiceBusBroker (Azure production)")
        return ServiceBusBroker()
    else:
        logger.info("Using KafkaBroker (local development)")
        return KafkaBroker()
