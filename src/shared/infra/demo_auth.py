from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.shared.config import get_settings


class DemoAuthMiddleware(BaseHTTPMiddleware):
    """Injects a local demo user identity when AUTH_MODE=anonymous."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        settings = get_settings()
        if settings.provider.auth_mode.lower() == "anonymous":
            header_user = request.headers.get("X-Demo-User", "").strip()
            request.state.user_id = header_user or "demo-user"
            request.state.user_role = request.headers.get("X-User-Role", "user").strip().lower()
        return await call_next(request)
