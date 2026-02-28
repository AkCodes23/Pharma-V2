"""
Unit tests for WebSocket Connection Manager and Web PubSub.

Tests local ConnectionManager events and WebPubSubManager
with mocked Azure SDK.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.shared.infra.websocket import (
    ConnectionManager,
    WebPubSubManager,
    REPLAY_BUFFER_SIZE,
)


class TestConnectionManager:
    """Tests for the in-memory WebSocket connection manager."""

    def setup_method(self) -> None:
        self.manager = ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect_registers_client(self) -> None:
        mock_ws = AsyncMock()
        await self.manager.connect(mock_ws, "session-1")

        assert "session-1" in self.manager._connections
        assert mock_ws in self.manager._connections["session-1"]
        mock_ws.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self) -> None:
        mock_ws = AsyncMock()
        await self.manager.connect(mock_ws, "session-1")
        await self.manager.disconnect(mock_ws, "session-1")

        assert "session-1" not in self.manager._connections

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_clients(self) -> None:
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await self.manager.connect(ws1, "session-1")
        await self.manager.connect(ws2, "session-1")

        await self.manager.broadcast("session-1", "task_update", {"status": "running"})

        ws1.send_text.assert_called()
        ws2.send_text.assert_called()

        # Verify message format
        sent_msg = json.loads(ws1.send_text.call_args[0][0])
        assert sent_msg["event"] == "task_update"
        assert sent_msg["data"]["status"] == "running"

    @pytest.mark.asyncio
    async def test_broadcast_cleans_dead_connections(self) -> None:
        ws_alive = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = Exception("Connection closed")

        await self.manager.connect(ws_alive, "session-1")
        await self.manager.connect(ws_dead, "session-1")

        await self.manager.broadcast("session-1", "update", {"x": 1})

        # Dead connection should be removed
        assert ws_dead not in self.manager._connections.get("session-1", set())

    @pytest.mark.asyncio
    async def test_replay_buffer(self) -> None:
        ws1 = AsyncMock()
        await self.manager.connect(ws1, "session-1")
        await self.manager.broadcast("session-1", "event1", {"n": 1})
        await self.manager.broadcast("session-1", "event2", {"n": 2})
        await self.manager.disconnect(ws1, "session-1")

        # New client should receive replayed events
        ws2 = AsyncMock()
        await self.manager.connect(ws2, "session-1")

        # accept() + replayed messages
        assert ws2.send_text.call_count >= 2

    @pytest.mark.asyncio
    async def test_replay_buffer_size_limit(self) -> None:
        ws = AsyncMock()
        await self.manager.connect(ws, "session-1")

        for i in range(REPLAY_BUFFER_SIZE + 5):
            await self.manager.broadcast("session-1", "event", {"n": i})

        assert len(self.manager._replay_buffers["session-1"]) == REPLAY_BUFFER_SIZE

    def test_clear_session_buffer(self) -> None:
        from collections import deque
        self.manager._replay_buffers["session-1"] = deque(["msg1", "msg2"])
        self.manager.clear_session_buffer("session-1")
        assert "session-1" not in self.manager._replay_buffers

    @pytest.mark.asyncio
    async def test_broadcast_raw(self) -> None:
        ws = AsyncMock()
        await self.manager.connect(ws, "session-1")
        await self.manager.broadcast_raw("session-1", '{"event":"test"}')
        ws.send_text.assert_called_with('{"event":"test"}')


class TestWebPubSubManager:
    """Tests for Azure Web PubSub manager."""

    def test_get_client_token_no_config(self) -> None:
        manager = WebPubSubManager()
        result = manager.get_client_token("session-1")
        assert "error" in result or result["url"] == ""

    @patch("src.shared.infra.websocket.get_settings")
    def test_broadcast_noop_without_client(self, mock_settings: MagicMock) -> None:
        manager = WebPubSubManager()
        # Should not raise even without PubSub client
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(manager.broadcast("session-1", "test", {}))
        finally:
            loop.close()

    @pytest.mark.asyncio
    async def test_connect_is_noop(self) -> None:
        manager = WebPubSubManager()
        mock_ws = AsyncMock()
        await manager.connect(mock_ws, "session-1")
        # Should not call accept — PubSub handles connections

    @pytest.mark.asyncio
    async def test_disconnect_is_noop(self) -> None:
        manager = WebPubSubManager()
        mock_ws = AsyncMock()
        await manager.disconnect(mock_ws, "session-1")
        # Should not raise
