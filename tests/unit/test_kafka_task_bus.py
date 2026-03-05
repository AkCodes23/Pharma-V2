from __future__ import annotations

import sys
import types

if "aiokafka" not in sys.modules:
    aiokafka_stub = types.ModuleType("aiokafka")
    aiokafka_stub.AIOKafkaConsumer = object
    aiokafka_stub.AIOKafkaProducer = object
    sys.modules["aiokafka"] = aiokafka_stub
from unittest.mock import AsyncMock

from src.shared.adapters.kafka_task_bus import KafkaTaskBusAdapterFactory, KafkaTaskBusPublisher
from src.shared.models.enums import PillarType
from src.shared.models.schemas import ServiceBusMessage, TaskNode


class _FakeProducer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []

    async def send_and_wait(self, topic: str, value: dict, key: str | None = None) -> None:
        self.calls.append((topic, value, key or ""))


def _message() -> ServiceBusMessage:
    task = TaskNode(
        session_id="session-1",
        pillar=PillarType.LEGAL,
        description="Legal fixture task",
        parameters={"drug_name": "Pembrolizumab"},
    )
    return ServiceBusMessage(session_id="session-1", task=task)


def test_kafka_publisher_routes_to_pillar_topic(monkeypatch) -> None:
    publisher = KafkaTaskBusPublisher()
    fake_producer = _FakeProducer()
    monkeypatch.setattr(publisher, "_ensure_producer", AsyncMock(return_value=fake_producer))
    monkeypatch.setattr(publisher, "_run", lambda coro, timeout=60: __import__("asyncio").run(coro))

    message = _message()
    publisher.publish_task(message)

    assert len(fake_producer.calls) == 1
    topic, payload, key = fake_producer.calls[0]
    assert topic == "pharma.tasks.legal"
    assert payload["data"]["session_id"] == "session-1"
    assert key == "session-1"


def test_kafka_task_bus_factory_creates_consumer_and_publisher() -> None:
    factory = KafkaTaskBusAdapterFactory()
    publisher = factory.create_publisher()
    consumer = factory.create_consumer(PillarType.NEWS, "retriever-news-sub")

    assert publisher is not None
    assert consumer is not None

