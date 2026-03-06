from __future__ import annotations

from unittest.mock import MagicMock

from src.agents.supervisor.main import SupervisorAgent
from src.shared.models.enums import SessionStatus, TaskStatus
from src.shared.models.schemas import ValidationResult


def test_supervisor_allows_validation_when_task_failed(monkeypatch) -> None:
    session = MagicMock()
    session.user_id = "demo-user"
    session.agent_results = []
    session.task_graph = [MagicMock(status=TaskStatus.FAILED)]

    store = MagicMock()
    store.get_session.return_value = session

    audit = MagicMock()
    agent = SupervisorAgent(store, audit)

    validation = ValidationResult(
        is_valid=False,
        conflicts=[],
        grounding_score=0.0,
        validation_notes="demo",
    )
    monkeypatch.setattr(agent._validator, "validate", lambda results: validation)

    assert agent.process_session("session-1") is True
    store.update_session_status.assert_called_once_with("session-1", SessionStatus.VALIDATING)
