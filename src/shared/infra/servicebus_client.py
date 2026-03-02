"""
Pharma Agentic AI — Azure Service Bus Client.

Topic-based message routing for the distributed agent swarm.
The Planner publishes tasks; Retriever agents consume them.

Architecture context:
  - Service: Shared infrastructure
  - Responsibility: Asynchronous message routing between agents
  - Upstream: Planner Agent (publisher)
  - Downstream: Retriever Agent Swarm (consumers)
  - Failure: Dead Letter Queue (DLQ) for unprocessable messages

Performance optimizations:
  - Sender caching: Reuse AMQP senders per topic (avoid reconnect overhead)
  - Batch publishing: Send multiple tasks in a single AMQP frame
  - Prefetch: Consumer prefetches 10 messages to reduce round-trips
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from azure.servicebus import (
    ServiceBusClient,
    ServiceBusMessage as AzureMessage,
    ServiceBusMessageBatch,
    ServiceBusReceiver,
    ServiceBusSender,
)
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.shared.config import get_settings
from src.shared.models.enums import PillarType
from src.shared.models.schemas import ServiceBusMessage

logger = logging.getLogger(__name__)


class ServiceBusPublisher:
    """
    Publishes task messages to Azure Service Bus topics.

    Routes messages to the correct topic based on PillarType.
    Used by the Planner Agent.

    Performance: Senders are cached per topic to avoid the overhead
    of establishing a new AMQP connection on every publish.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = ServiceBusClient.from_connection_string(
            conn_str=settings.servicebus.connection_string,
        )
        self._topic_map: dict[PillarType, str] = {
            PillarType.LEGAL: settings.servicebus.legal_topic,
            PillarType.CLINICAL: settings.servicebus.clinical_topic,
            PillarType.COMMERCIAL: settings.servicebus.commercial_topic,
            PillarType.SOCIAL: settings.servicebus.social_topic,
            PillarType.KNOWLEDGE: settings.servicebus.knowledge_topic,
            PillarType.NEWS: settings.servicebus.news_topic,
        }
        # ── Cached senders (one per topic, reused across publishes) ──
        self._senders: dict[str, ServiceBusSender] = {}
        logger.info("ServiceBusPublisher initialized with %d topics", len(self._topic_map))

    def _get_sender(self, topic_name: str) -> ServiceBusSender:
        """
        Get or create a cached sender for the given topic.

        Senders are long-lived AMQP connections. Creating one per
        publish call wastes ~50ms per message on connection setup.
        Caching eliminates this overhead entirely.

        Time complexity: O(1) dict lookup.
        Space complexity: O(T) where T = number of topics (max 5).
        """
        if topic_name not in self._senders:
            self._senders[topic_name] = self._client.get_topic_sender(topic_name=topic_name)
            logger.debug("Created cached sender for topic: %s", topic_name)
        return self._senders[topic_name]

    def _build_azure_message(self, message: ServiceBusMessage) -> AzureMessage:
        """Build an Azure Service Bus message from our domain model."""
        payload = message.model_dump_json()
        azure_msg = AzureMessage(body=payload)
        azure_msg.message_id = message.message_id
        azure_msg.correlation_id = message.correlation_id
        azure_msg.subject = message.task.pillar.value
        azure_msg.application_properties = {
            "session_id": message.session_id,
            "pillar": message.task.pillar.value,
            "task_id": message.task.task_id,
        }
        return azure_msg

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception(lambda e: not isinstance(e, KeyError)),
    )
    def publish_task(self, message: ServiceBusMessage) -> None:
        """
        Publish a single task message to the appropriate Service Bus topic.

        Routing is determined by the task's PillarType.
        Uses cached senders to avoid AMQP reconnection overhead.

        Args:
            message: Validated ServiceBusMessage with embedded TaskNode.

        Raises:
            KeyError: If the pillar type has no configured topic.
            ServiceBusError: On persistent Service Bus failures.
        """
        pillar = message.task.pillar
        topic_name = self._topic_map.get(pillar)
        if not topic_name:
            raise KeyError(f"No Service Bus topic configured for pillar: {pillar}")

        sender = self._get_sender(topic_name)
        azure_msg = self._build_azure_message(message)
        sender.send_messages(azure_msg)

        logger.info(
            "Task published to Service Bus",
            extra={
                "topic": topic_name,
                "pillar": pillar,
                "session_id": message.session_id,
                "task_id": message.task.task_id,
            },
        )

    def publish_batch(self, messages: list[ServiceBusMessage]) -> int:
        """
        Publish multiple tasks in a single AMQP batch per topic.

        Groups messages by pillar, creates a batch for each topic,
        and sends them in one network round-trip per topic.

        This is ~5x faster than sequential publish_task() calls
        when the Planner creates all 5 pillar tasks at once.

        Args:
            messages: List of ServiceBusMessages to publish.

        Returns:
            Total number of messages successfully published.

        Raises:
            ServiceBusError: On persistent failures after retries.
        """
        # Group messages by topic
        topic_groups: dict[str, list[ServiceBusMessage]] = {}
        for msg in messages:
            topic_name = self._topic_map.get(msg.task.pillar)
            if not topic_name:
                logger.warning("Skipping message with unknown pillar: %s", msg.task.pillar)
                continue
            topic_groups.setdefault(topic_name, []).append(msg)

        total_sent = 0
        for topic_name, group in topic_groups.items():
            sender = self._get_sender(topic_name)
            batch: ServiceBusMessageBatch = sender.create_message_batch()

            for msg in group:
                azure_msg = self._build_azure_message(msg)
                try:
                    batch.add_message(azure_msg)
                except ValueError:
                    # Batch is full — send current batch and start new one
                    sender.send_messages(batch)
                    total_sent += len(batch)  # type: ignore[arg-type]
                    batch = sender.create_message_batch()
                    batch.add_message(azure_msg)

            if len(batch) > 0:  # type: ignore[arg-type]
                sender.send_messages(batch)
                total_sent += len(batch)  # type: ignore[arg-type]

            logger.info(
                "Batch published to topic",
                extra={"topic": topic_name, "count": len(group)},
            )

        return total_sent

    def close(self) -> None:
        """Close all cached senders and the Service Bus client connection."""
        for topic_name, sender in self._senders.items():
            try:
                sender.close()
                logger.debug("Closed cached sender for topic: %s", topic_name)
            except Exception:
                logger.warning("Failed to close sender for topic: %s", topic_name, exc_info=True)
        self._senders.clear()
        self._client.close()
        logger.info("ServiceBusPublisher closed (all senders released)")


class ServiceBusConsumer:
    """
    Consumes task messages from an Azure Service Bus subscription.

    Used by Retriever Agents. Each agent type subscribes to its
    pillar-specific topic.

    Performance: Prefetch count of 10 reduces AMQP round-trips
    for bursty workloads (e.g., when Planner publishes all tasks).
    """

    # Prefetch reduces latency by pre-fetching messages from the broker
    # before the application requests them. Value of 10 is optimal for
    # our workload (5 pillars × ~2 tasks per query).
    PREFETCH_COUNT = 10

    def __init__(self, pillar: PillarType, subscription_name: str) -> None:
        """
        Initialize a consumer for a specific pillar topic.

        Args:
            pillar: The pillar type to consume messages for.
            subscription_name: The subscription name (typically the agent instance ID).
        """
        settings = get_settings()
        self._client = ServiceBusClient.from_connection_string(
            conn_str=settings.servicebus.connection_string,
        )
        topic_map: dict[PillarType, str] = {
            PillarType.LEGAL: settings.servicebus.legal_topic,
            PillarType.CLINICAL: settings.servicebus.clinical_topic,
            PillarType.COMMERCIAL: settings.servicebus.commercial_topic,
            PillarType.SOCIAL: settings.servicebus.social_topic,
            PillarType.KNOWLEDGE: settings.servicebus.knowledge_topic,
            PillarType.NEWS: settings.servicebus.news_topic,
        }
        self._topic_name = topic_map[pillar]
        self._subscription_name = subscription_name
        self._pillar = pillar
        self._running = False
        logger.info(
            "ServiceBusConsumer initialized",
            extra={"topic": self._topic_name, "subscription": subscription_name},
        )

    def consume(
        self,
        handler: Callable[[ServiceBusMessage], None],
        max_messages: int = 1,
        max_wait_time: int = 30,
    ) -> None:
        """
        Start consuming messages from the subscription.

        Messages are deserialized into ServiceBusMessage objects and
        passed to the handler. Successfully processed messages are
        completed; failed messages are dead-lettered.

        Performance: Uses prefetch to reduce round-trips. The
        prefetch_count is set on the receiver to pre-fetch messages.

        Args:
            handler: Callback function to process each message.
            max_messages: Max messages to receive per batch.
            max_wait_time: Max seconds to wait for messages.
        """
        self._running = True
        receiver: ServiceBusReceiver = self._client.get_subscription_receiver(
            topic_name=self._topic_name,
            subscription_name=self._subscription_name,
            max_wait_time=max_wait_time,
            prefetch_count=self.PREFETCH_COUNT,
        )

        logger.info(
            "Starting message consumption loop",
            extra={"topic": self._topic_name, "prefetch": self.PREFETCH_COUNT},
        )

        with receiver:
            while self._running:
                messages = receiver.receive_messages(
                    max_message_count=max_messages,
                    max_wait_time=max_wait_time,
                )

                for msg in messages:
                    try:
                        body = str(msg)
                        parsed = ServiceBusMessage.model_validate_json(body)
                        handler(parsed)
                        receiver.complete_message(msg)
                        logger.info(
                            "Message processed successfully",
                            extra={
                                "task_id": parsed.task.task_id,
                                "session_id": parsed.session_id,
                            },
                        )
                    except Exception:
                        logger.exception(
                            "Failed to process message, sending to DLQ",
                            extra={"message_id": msg.message_id},
                        )
                        receiver.dead_letter_message(
                            msg,
                            reason="ProcessingError",
                            error_description="Handler raised an unrecoverable exception",
                        )

    def stop(self) -> None:
        """Signal the consumption loop to stop."""
        self._running = False
        logger.info("ServiceBusConsumer stop signal sent")

    def close(self) -> None:
        """Close the Service Bus client connection."""
        self.stop()
        self._client.close()
        logger.info("ServiceBusConsumer closed")
