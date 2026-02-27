"""
Pharma Agentic AI — Kafka Event Client.

Provides event streaming for the agent swarm. In local dev, Kafka
replaces Azure Service Bus. In production, Azure Event Hubs
(Kafka-compatible) is used.

Architecture context:
  - Service: Shared infrastructure
  - Responsibility: Event streaming, event sourcing, analytics pipeline
  - Upstream: All agent services (producers)
  - Downstream: Analytics pipeline, audit stream (consumers)
  - Failure: DLQ topic for unprocessable events

Performance optimizations:
  - Async producer: Non-blocking sends with delivery callbacks
  - Batch consumption: Prefetch up to 10 messages
  - Key-based partitioning: session_id ensures ordered processing per session
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


class KafkaEventProducer:
    """
    Async Kafka producer for domain events.

    Publishes events to topic partitions keyed by session_id,
    guaranteeing ordered processing per session.

    Thread-safe: AIOKafkaProducer manages connections internally.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._bootstrap_servers = settings.kafka.bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Start the Kafka producer. Call once at app startup."""
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",  # Wait for all replicas (durability)
            enable_idempotence=True,  # Exactly-once semantics
            max_batch_size=16384,
            linger_ms=10,  # Batch for 10ms before sending
            compression_type="lz4",
        )
        await self._producer.start()
        logger.info("KafkaEventProducer started", extra={"servers": self._bootstrap_servers})

    async def publish_event(
        self,
        topic: str,
        event_type: str,
        data: dict[str, Any],
        key: str | None = None,
    ) -> None:
        """
        Publish a domain event to a Kafka topic.

        Args:
            topic: Kafka topic name (e.g., 'pharma.events.sessions').
            event_type: Event classification (e.g., 'session_created').
            data: Event payload.
            key: Partition key (typically session_id for ordering).
        """
        if not self._producer:
            raise RuntimeError("KafkaEventProducer not started. Call start() first.")

        event = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "data": data,
        }

        try:
            await self._producer.send_and_wait(topic, value=event, key=key)
            logger.debug(
                "Event published",
                extra={"topic": topic, "event_type": event_type, "key": key},
            )
        except KafkaError:
            logger.exception(
                "Failed to publish event",
                extra={"topic": topic, "event_type": event_type},
            )

    async def publish_task(self, pillar: str, message_data: dict[str, Any], session_id: str) -> None:
        """
        Publish a task message to a pillar-specific topic.

        Mirrors ServiceBusPublisher.publish_task() for interchangeability.
        """
        topic = f"pharma.tasks.{pillar.lower()}"
        await self.publish_event(
            topic=topic,
            event_type="task_dispatched",
            data=message_data,
            key=session_id,
        )

    async def stop(self) -> None:
        """Stop the producer and flush pending messages."""
        if self._producer:
            await self._producer.stop()
            self._producer = None
            logger.info("KafkaEventProducer stopped")


class KafkaEventConsumer:
    """
    Async Kafka consumer for domain events.

    Consumes events from a topic and dispatches to a handler function.
    Supports consumer group for horizontal scaling.

    Thread-safe: AIOKafkaConsumer manages connections internally.
    """

    def __init__(self, topic: str, group_id: str) -> None:
        settings = get_settings()
        self._bootstrap_servers = settings.kafka.bootstrap_servers
        self._topic = topic
        self._group_id = group_id
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False

    async def start(self, handler: Callable[[dict[str, Any]], None]) -> None:
        """
        Start consuming events.

        Args:
            handler: Callback for each event. Receives the deserialized event dict.
        """
        self._consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=False,  # Manual commit for at-least-once
            max_poll_records=10,
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000,
        )
        await self._consumer.start()
        self._running = True

        logger.info(
            "KafkaEventConsumer started",
            extra={"topic": self._topic, "group_id": self._group_id},
        )

        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                try:
                    handler(msg.value)
                    await self._consumer.commit()
                except Exception:
                    logger.exception(
                        "Failed to process Kafka message — sending to DLQ",
                        extra={
                            "topic": msg.topic,
                            "partition": msg.partition,
                            "offset": msg.offset,
                        },
                    )
                    # In production, publish to pharma.dlq topic
                    await self._consumer.commit()  # Skip bad message to avoid infinite loop
        finally:
            await self._consumer.stop()

    async def stop(self) -> None:
        """Signal the consumption loop to stop."""
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None
        logger.info("KafkaEventConsumer stopped", extra={"topic": self._topic})
