from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from src.agents.executor.main import ExecutorAgent
from src.agents.planner.publisher import TaskPublisher
from src.agents.supervisor.main import SupervisorAgent
from src.demo.fixture_loader import get_fixture_loader
from src.shared.adapters.fixture_decomposer import FixtureDecomposer
from src.shared.adapters.fixture_report_generator import FixtureReportGenerator
from src.shared.config import get_settings
from src.shared.models.enums import (
    AgentType,
    DecisionOutcome,
    SessionStatus,
    TaskStatus,
)
from src.shared.models.schemas import AgentResult, AuditEntry, Citation, Session, ValidationResult


@dataclass
class InMemorySessionStore:
    sessions: dict[str, Session] = field(default_factory=dict)
    audits: list[AuditEntry] = field(default_factory=list)

    def ensure_containers(self) -> None:
        return

    def create_session(self, session: Session) -> dict[str, Any]:
        self.sessions[session.id] = session
        return session.model_dump(mode="json")

    def get_session(self, session_id: str) -> Session:
        return self.sessions[session_id]

    def get_session_with_etag(self, session_id: str) -> tuple[Session, str]:
        session = self.get_session(session_id)
        return session, session.updated_at.isoformat()

    def update_session_status(self, session_id: str, status: SessionStatus) -> None:
        session = self.get_session(session_id)
        session.status = status
        session.updated_at = datetime.now(timezone.utc)

    def add_task_to_session(self, session_id: str, task) -> None:
        session = self.get_session(session_id)
        session.task_graph.append(task)

    def update_task_status(self, session_id: str, task_id: str, status: TaskStatus, error_message: str | None = None) -> None:
        session = self.get_session(session_id)
        for task in session.task_graph:
            if task.task_id == task_id:
                task.status = status
                task.error_message = error_message
                if status == TaskStatus.COMPLETED:
                    task.completed_at = datetime.now(timezone.utc)
                break

    def add_agent_result(self, session_id: str, result: AgentResult) -> None:
        self.get_session(session_id).agent_results.append(result)

    def set_validation_result(self, session_id: str, validation: ValidationResult) -> None:
        session = self.get_session(session_id)
        session.validation = validation
        session.status = SessionStatus.VALIDATING

    def complete_session(self, session_id: str, decision: str, rationale: str, report_url: str | None = None, excel_url: str | None = None) -> None:
        session = self.get_session(session_id)
        session.status = SessionStatus.COMPLETED
        session.decision = DecisionOutcome(decision)
        session.decision_rationale = rationale
        session.report_url = report_url
        session.excel_url = excel_url
        session.completed_at = datetime.now(timezone.utc)

    def write_audit_entry(self, entry: AuditEntry) -> None:
        self.audits.append(entry)

    def write_audit_entries(self, entries: list[AuditEntry]) -> int:
        self.audits.extend(entries)
        return len(entries)

    def query_audit_trail(self, session_id: str, limit: int = 100) -> list[AuditEntry]:
        return [entry for entry in self.audits if entry.session_id == session_id][:limit]

    def list_sessions(self, *, drug_name: str = "", user_id: str = "", status: str = "", limit: int = 10, offset: int = 0) -> tuple[list[Session], int]:
        sessions = list(self.sessions.values())
        if status:
            sessions = [s for s in sessions if s.status.value == status]
        total = len(sessions)
        return sessions[offset : offset + limit], total

    def list_audit_entries(self, *, limit: int = 100, session_id: str = "") -> list[AuditEntry]:
        entries = self.audits
        if session_id:
            entries = [e for e in entries if e.session_id == session_id]
        return entries[:limit]


class FakeTaskBus:
    def __init__(self) -> None:
        self.messages = []

    def publish_task(self, message) -> None:
        self.messages.append(message)

    def publish_batch(self, messages) -> int:
        self.messages.extend(messages)
        return len(messages)

    def close(self) -> None:
        return


def test_standalone_session_flow_reaches_completed(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_MODE", "standalone_demo")
    monkeypatch.setenv("DEMO_OFFLINE", "true")
    monkeypatch.setenv("DATA_STORE_PROVIDER", "postgres")
    monkeypatch.setenv("TASK_BUS_PROVIDER", "kafka")
    monkeypatch.setenv("OBJECT_STORE_PROVIDER", "minio")
    monkeypatch.setenv("LLM_PROVIDER", "fixture")
    monkeypatch.setenv("KNOWLEDGE_PROVIDER", "fixture")
    monkeypatch.setenv("AUTH_MODE", "anonymous")
    monkeypatch.setenv("MINIO_ENDPOINT", "minio:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_SECRET_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_BUCKET", "reports")
    monkeypatch.setenv("POSTGRES_URL", "postgresql://pharma:pass@localhost:5432/pharma_ai")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    monkeypatch.setenv("SUPERVISOR_URL", "http://localhost:8001")
    monkeypatch.setenv("EXECUTOR_URL", "http://localhost:8002")

    session_store = InMemorySessionStore()
    task_bus = FakeTaskBus()
    audit = MagicMock()

    decomposer = FixtureDecomposer()
    params, tasks = decomposer.decompose("Assess 2027 generic launch for Keytruda in India", "session-1")

    publisher = TaskPublisher(session_store, task_bus, audit)
    session = publisher.publish(
        query="Assess 2027 generic launch for Keytruda in India",
        user_id="demo-user",
        parameters=params,
        tasks=tasks,
        session_id="session-1",
        correlation_id="trace-1",
    )

    assert session.status == SessionStatus.RETRIEVING
    assert session_store.get_session("session-1").status == SessionStatus.RETRIEVING

    fixture_loader = get_fixture_loader()
    for message in task_bus.messages:
        task = message.task
        session_store.update_task_status("session-1", task.task_id, TaskStatus.RUNNING)
        findings, raw_citations = fixture_loader.load_retriever_output(task.pillar, task)
        result = AgentResult(
            task_id=task.task_id,
            session_id="session-1",
            agent_type=AgentType[f"{task.pillar.value}_RETRIEVER"],
            pillar=task.pillar,
            findings=findings,
            citations=[Citation.model_validate(c) for c in raw_citations],
            confidence=0.9,
            execution_time_ms=50,
        )
        session_store.add_agent_result("session-1", result)
        session_store.update_task_status("session-1", task.task_id, TaskStatus.COMPLETED)

    supervisor = SupervisorAgent(session_store, MagicMock())
    assert supervisor.process_session("session-1") is True
    assert session_store.get_session("session-1").status == SessionStatus.VALIDATING

    monkeypatch.setattr("src.agents.executor.main.create_report_engine", lambda: FixtureReportGenerator())
    executor = ExecutorAgent(session_store, MagicMock())
    monkeypatch.setattr(executor._pdf_engine, "render_pdf", lambda **_: b"")

    output = executor.execute("session-1")

    final_session = session_store.get_session("session-1")
    assert final_session.status == SessionStatus.COMPLETED
    assert final_session.decision is not None
    assert output["decision"] == final_session.decision.value
    assert output["report_url"]
