from __future__ import annotations

from typing import Protocol

from src.shared.models.schemas import QueryParameters, TaskNode


class DecompositionEngine(Protocol):
    """Intent decomposition contract."""

    def decompose(self, query: str, session_id: str) -> tuple[QueryParameters, list[TaskNode]]: ...

    def close(self) -> None: ...
