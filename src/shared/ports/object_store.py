from __future__ import annotations

from typing import Protocol


class ObjectStore(Protocol):
    """Binary artifact storage contract."""

    def ensure_ready(self) -> None: ...

    def upload_bytes(
        self,
        *,
        session_id: str,
        filename: str,
        payload: bytes,
        content_type: str = "application/octet-stream",
    ) -> str: ...
