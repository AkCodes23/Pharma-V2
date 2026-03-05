from __future__ import annotations

from typing import Callable, Protocol

from src.shared.models.enums import PillarType
from src.shared.models.schemas import ServiceBusMessage


class TaskBusPublisher(Protocol):
    """Publish task graph messages."""

    def publish_task(self, message: ServiceBusMessage) -> None: ...

    def publish_batch(self, messages: list[ServiceBusMessage]) -> int: ...

    def close(self) -> None: ...


class TaskBusConsumer(Protocol):
    """Consume task graph messages."""

    def consume(
        self,
        handler: Callable[[ServiceBusMessage], None],
        max_messages: int = 10,
        max_wait_time: int = 30,
    ) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


class TaskBusFactory(Protocol):
    """Factory contract for creating publisher and consumer objects."""

    def create_publisher(self) -> TaskBusPublisher: ...

    def create_consumer(self, pillar: PillarType, subscription_name: str) -> TaskBusConsumer: ...
