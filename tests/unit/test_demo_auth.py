from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.shared.config import get_settings
from src.shared.infra.demo_auth import DemoAuthMiddleware


def test_demo_auth_ignores_caller_supplied_admin_role(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_MODE", "standalone_demo")
    monkeypatch.setenv("AUTH_MODE", "anonymous")

    app = FastAPI()
    app.add_middleware(DemoAuthMiddleware)

    @app.get("/me")
    async def me(request: Request) -> dict[str, str]:
        return {
            "user_id": request.state.user_id,
            "user_role": request.state.user_role,
        }

    with TestClient(app) as client:
        response = client.get(
            "/me",
            headers={"X-Demo-User": "alice", "X-User-Role": "admin"},
        )

    assert response.status_code == 200
    assert response.json() == {"user_id": "alice", "user_role": "user"}


def test_demo_auth_defaults_demo_user(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_MODE", "standalone_demo")
    monkeypatch.setenv("AUTH_MODE", "anonymous")

    app = FastAPI()
    app.add_middleware(DemoAuthMiddleware)

    @app.get("/me")
    async def me(request: Request) -> dict[str, str]:
        return {"user_id": request.state.user_id}

    with TestClient(app) as client:
        response = client.get("/me")

    assert response.status_code == 200
    assert response.json() == {"user_id": "demo-user"}
