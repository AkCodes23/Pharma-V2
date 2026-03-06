from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import threading
from typing import Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from src.shared.config import get_settings
from src.shared.models.enums import PillarType
from src.shared.models.schemas import ServiceBusMessage
from src.shared.ports.task_bus import TaskBusConsumer, TaskBusFactory, TaskBusPublisher

logger = logging.getLogger(__name__)


def _pillar_topic(pillar: PillarType) -> str:
    """Map pillar enums to the source-of-truth topic naming contract."""
    return f"{pillar.value.lower()}-tasks"


class _AsyncRunner:
    def _run(self, coro: object, *, timeout: int = 60) -> object:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)  # type: ignore[arg-type]
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=timeout)


class KafkaTaskBusPublisher(_AsyncRunner, TaskBusPublisher):
    def __init__(self) -> None:
        self._bootstrap = get_settings().kafka.bootstrap_servers

    async def _publish_batch_async(self, messages: list[ServiceBusMessage]) -> int:
        if not messages:
            return 0

        producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda v: v.encode("utf-8") if v else None,
            acks="all",
        )
        await producer.start()
        try:
            for message in messages:
                topic = _pillar_topic(message.task.pillar)
                payload = {"event_type": "task_dispatched", "data": message.model_dump(mode="json")}
                await producer.send_and_wait(topic=topic, value=payload, key=message.session_id)
        finally:
            await producer.stop()

        return len(messages)

    def publish_task(self, message: ServiceBusMessage) -> None:
        self._run(self._publish_batch_async([message]))

    def publish_batch(self, messages: list[ServiceBusMessage]) -> int:
        return int(self._run(self._publish_batch_async(messages)))

    def close(self) -> None:
        return


class KafkaTaskBusConsumer(_AsyncRunner, TaskBusConsumer):
    def __init__(self, pillar: PillarType, subscription_name: str) -> None:
        self._pillar = pillar
        self._subscription_name = subscription_name
        self._bootstrap = get_settings().kafka.bootstrap_servers
        self._stop_event = threading.Event()

    async def _consume_loop(
        self,
        handler: Callable[[ServiceBusMessage], None],
        max_messages: int,
        max_wait_time: int,
    ) -> None:
        topic = _pillar_topic(self._pillar)
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=self._bootstrap,
            group_id=self._subscription_name,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000,
        )

        await consumer.start()
        logger.info(
            "Kafka task consumer started",
            extra={"topic": topic, "group_id": self._subscription_name},
        )
        try:
            while not self._stop_event.is_set():
                batches = await consumer.getmany(
                    timeout_ms=max_wait_time * 1000,
                    max_records=max_messages,
                )
                for _, records in batches.items():
                    for record in records:
                        event = record.value
                        payload = event.get("data", event)
                        message = ServiceBusMessage.model_validate(payload)
                        handler(message)
                if batches:
                    await consumer.commit()
        finally:
            await consumer.stop()

    def consume(
        self,
        handler: Callable[[ServiceBusMessage], None],
        max_messages: int = 10,
        max_wait_time: int = 30,
    ) -> None:
        self._stop_event.clear()
        self._run(self._consume_loop(handler, max_messages, max_wait_time), timeout=3600)

    def stop(self) -> None:
        self._stop_event.set()

    def close(self) -> None:
        self._stop_event.set()


class KafkaTaskBusAdapterFactory(TaskBusFactory):
    def create_publisher(self) -> TaskBusPublisher:
        return KafkaTaskBusPublisher()

    def create_consumer(self, pillar: PillarType, subscription_name: str) -> TaskBusConsumer:
        return KafkaTaskBusConsumer(pillar=pillar, subscription_name=subscription_name)
