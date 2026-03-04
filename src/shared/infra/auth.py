from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request


def _is_dev_mode() -> bool:
    return os.getenv("APP_ENV", "development").lower() in {"development", "dev", "local", "test"}


def get_request_user_id(request: Request) -> str:
    """Resolve caller identity from trusted header."""
    user_id = request.headers.get("X-User-Id", "").strip()
    if user_id:
        return user_id

    if _is_dev_mode():
        return "dev-user"

    raise HTTPException(status_code=401, detail="Missing authenticated user identity")


def require_authenticated_user(user_id: Annotated[str, Depends(get_request_user_id)]) -> str:
    return user_id


def is_admin_request(request: Request) -> bool:
    role = request.headers.get("X-User-Role", "").strip().lower()
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

    If PHARMA_INTERNAL_API_KEY is unset in development/test, auth is skipped for local/dev compatibility.
    In non-dev environments, a missing key is treated as a server misconfiguration and fails closed.
    """
    expected = os.getenv("PHARMA_INTERNAL_API_KEY", "")
    if not expected:
        if _is_dev_mode():
            # In dev/test, allow running without configuring an internal API key.
            return
        # In non-dev environments, fail closed if the internal API key is not configured.
        raise HTTPException(status_code=500, detail="Internal API key is not configured")

    supplied = request.headers.get("X-API-Key", "")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid internal API key")
