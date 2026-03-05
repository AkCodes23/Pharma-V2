from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from src.shared.config import get_settings


def _is_dev_mode() -> bool:
    return os.getenv("APP_ENV", "development").lower() in {"development", "dev", "local", "test"}


def _auth_mode() -> str:
    try:
        return get_settings().provider.auth_mode.lower()
    except Exception:
        return os.getenv("AUTH_MODE", "header").lower()


def get_request_user_id(request: Request) -> str:
    """Resolve caller identity from trusted headers or demo-mode middleware."""
    if _auth_mode() == "anonymous":
        state_user = getattr(request.state, "user_id", "").strip() if hasattr(request, "state") else ""
        if state_user:
            return state_user
        header_user = request.headers.get("X-Demo-User", "").strip()
        return header_user or "demo-user"

    user_id = request.headers.get("X-User-Id", "").strip()
    if user_id:
        return user_id

    if _is_dev_mode():
        return "dev-user"

    raise HTTPException(status_code=401, detail="Missing authenticated user identity")


def require_authenticated_user(user_id: Annotated[str, Depends(get_request_user_id)]) -> str:
    return user_id


def is_admin_request(request: Request) -> bool:
    state_role = getattr(request.state, "user_role", "").strip().lower() if hasattr(request, "state") else ""
    role = state_role or request.headers.get("X-User-Role", "").strip().lower()
    return role == "admin"


def require_admin_user(
    request: Request,
    user_id: Annotated[str, Depends(get_request_user_id)],
) -> str:
    if is_admin_request(request):
        return user_id
    raise HTTPException(status_code=403, detail="Admin role required")


def require_internal_api_key(request: Request) -> None:
    """
    Validate service-to-service API key when configured.

    If PHARMA_INTERNAL_API_KEY is unset, auth is skipped for local/dev compatibility.
    """
    expected = os.getenv("PHARMA_INTERNAL_API_KEY", "")
    if not expected:
        return

    supplied = request.headers.get("X-API-Key", "")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid internal API key")
