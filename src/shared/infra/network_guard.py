from __future__ import annotations

from urllib.parse import urlparse

from src.shared.config import get_settings

_BLOCKED_AZURE_HOST_SNIPPETS = (
    ".azure.com",
    ".windows.net",
    "servicebus.windows.net",
)


def assert_url_allowed_for_demo(url: str) -> None:
    """Fail fast if standalone demo mode attempts Azure egress."""

    settings = get_settings()
    if not settings.demo_offline:
        return

    host = (urlparse(url).hostname or "").lower()
    if any(snippet in host for snippet in _BLOCKED_AZURE_HOST_SNIPPETS):
        raise RuntimeError(
            f"DEMO_OFFLINE blocks outbound request to Azure domain: {host}"
        )
