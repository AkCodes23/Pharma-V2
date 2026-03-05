from __future__ import annotations

import sys
import types

if "asyncpg" not in sys.modules:
    asyncpg_stub = types.ModuleType("asyncpg")
    asyncpg_stub.Pool = object

    async def _unsupported_create_pool(*args, **kwargs):
        raise RuntimeError("create_pool should be mocked in unit tests")

    asyncpg_stub.create_pool = _unsupported_create_pool
    sys.modules["asyncpg"] = asyncpg_stub
from src.shared.adapters.postgres_session_store import PostgresSessionStore
from src.shared.models.enums import SessionStatus, TaskStatus
from src.shared.models.schemas import QueryParameters, Session, TaskNode


def _build_session(session_id: str) -> Session:
    return Session(
        id=session_id,
        user_id="demo-user",
        query="Assess demo flow",
        parameters=QueryParameters(
            drug_name="Pembrolizumab",
            brand_name="Keytruda",
            target_market="India",
            time_horizon="2027",
            therapeutic_area="Oncology",
        ),
        task_graph=[
            TaskNode(
                session_id=session_id,
                pillar="LEGAL",
                description="Check patents",
                parameters={"drug_name": "Pembrolizumab"},
            )
        ],
    )


def test_postgres_session_store_updates_task_retry_count(monkeypatch) -> None:
    store = PostgresSessionStore.__new__(PostgresSessionStore)
    state: dict[str, dict] = {}

    async def _store_payload(session_id: str, payload: dict) -> None:
        state[session_id] = payload

    async def _fetch_payload(session_id: str) -> dict:
        return state[session_id]

    monkeypatch.setattr(store, "_store_session_payload", _store_payload)
    monkeypatch.setattr(store, "_fetch_session_payload", _fetch_payload)
    monkeypatch.setattr(store, "_run", lambda coro: __import__("asyncio").run(coro))

    session = _build_session("s-1")
    store.create_session(session)

    task_id = session.task_graph[0].task_id
    store.update_task_status("s-1", task_id, TaskStatus.RETRYING, error_message="temporary")

    loaded = store.get_session("s-1")
    assert loaded.task_graph[0].status == TaskStatus.RETRYING
    assert loaded.task_graph[0].retry_count == 1


def test_postgres_session_store_completes_session(monkeypatch) -> None:
    store = PostgresSessionStore.__new__(PostgresSessionStore)
    state: dict[str, dict] = {}

    async def _store_payload(session_id: str, payload: dict) -> None:
        state[session_id] = payload

    async def _fetch_payload(session_id: str) -> dict:
        return state[session_id]

    monkeypatch.setattr(store, "_store_session_payload", _store_payload)
    monkeypatch.setattr(store, "_fetch_session_payload", _fetch_payload)
    monkeypatch.setattr(store, "_run", lambda coro: __import__("asyncio").run(coro))

    session = _build_session("s-2")
    store.create_session(session)
    store.update_session_status("s-2", SessionStatus.SYNTHESIZING)
    store.complete_session("s-2", "GO", "Deterministic pass", report_url="http://minio/report.pdf")

    completed = store.get_session("s-2")
    assert completed.status == SessionStatus.COMPLETED
    assert completed.decision is not None
    assert completed.decision.value == "GO"
    assert completed.report_url == "http://minio/report.pdf"

