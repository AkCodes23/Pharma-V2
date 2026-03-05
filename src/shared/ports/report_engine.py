from __future__ import annotations

from typing import Protocol

from src.shared.models.enums import DecisionOutcome
from src.shared.models.schemas import Session


class ReportEngine(Protocol):
    """Report synthesis contract."""

    def generate_report(self, session: Session) -> tuple[str, DecisionOutcome, str]: ...

    def close(self) -> None: ...
