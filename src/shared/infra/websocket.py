"""
Pharma Agentic AI — WebSocket Connection Manager.

Handles real-time session updates from the backend to the
frontend dashboard via WebSocket connections.

Architecture context:
  - Service: Shared infrastructure (used by Planner Agent)
  - Responsibility: Real-time UI updates for session progress
  - Upstream: Agent pipeline (broadcasts events on status change)
  - Downstream: Frontend WebSocket clients
  - Scaling: In-memory per Container App instance
  - Failure: Graceful degradation; frontend falls back to polling

Performance optimizations:
  - Heartbeat timeout: Disconnect stale clients after 60s of silence
  - Message replay buffer: Ring buffer per session for reconnection
  - Dead connection cleanup: Automatic on broadcast failure
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Max events to buffer per session for replay on reconnection
REPLAY_BUFFER_SIZE = 20
# Seconds of silence before a client is considered stale
HEARTBEAT_TIMEOUT_SECONDS = 60.0


class ConnectionManager:
    """
    Manages WebSocket connections grouped by session ID.

    Features:
      - Multi-client: Multiple frontend tabs can watch the same session
      - Heartbeat timeout: Disconnects clients that haven't pinged in 60s
      - Message replay: Stores last N events per session for reconnection
      - Dead connection cleanup: Automatic on broadcast failure

    Thread-safety: Uses asyncio.Lock for connection set mutations.
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._last_ping: dict[WebSocket, float] = {}
        self._replay_buffers: dict[str, deque[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """
        Accept a WebSocket connection and register it for a session.

        On reconnection, replays the last N events so the client
        doesn't miss any updates.

        Args:
            websocket: The WebSocket connection to register.
            session_id: The session to watch for updates.
        """
        await websocket.accept()

        async with self._lock:
            if session_id not in self._connections:
                self._connections[session_id] = set()
            self._connections[session_id].add(websocket)
            self._last_ping[websocket] = time.monotonic()

        logger.info(
            "WebSocket client connected",
            extra={
                "session_id": session_id,
                "total_clients": len(self._connections.get(session_id, set())),
            },
        )

        # Replay buffered events on reconnection
        async with self._lock:
            buffer = self._replay_buffers.get(session_id, deque())
        for message in buffer:
            try:
                await websocket.send_text(message)
            except Exception:
                break

    async def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        """
        Remove a WebSocket connection from a session group.

        Cleans up empty session groups and ping tracking.
        """
        async with self._lock:
            if session_id in self._connections:
                self._connections[session_id].discard(websocket)
                if not self._connections[session_id]:
                    del self._connections[session_id]
            self._last_ping.pop(websocket, None)

        logger.info(
            "WebSocket client disconnected",
            extra={"session_id": session_id},
        )

    async def broadcast(self, session_id: str, event: str, data: dict[str, Any]) -> None:
        """
        Send an event to all clients watching a session.

        Also stores the message in the replay buffer for reconnection.

        Args:
            session_id: The session to broadcast to.
            event: Event type (task_update, validation, completed, error).
            data: Event payload.
        """
        message = json.dumps({"event": event, "data": data}, default=str)

        # Store in replay buffer
        async with self._lock:
            if session_id not in self._replay_buffers:
                self._replay_buffers[session_id] = deque(maxlen=REPLAY_BUFFER_SIZE)
            self._replay_buffers[session_id].append(message)
            connections = self._connections.get(session_id, set()).copy()

        dead_connections: list[WebSocket] = []

        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.append(ws)

        # Clean up dead connections
        if dead_connections:
            async with self._lock:
                for ws in dead_connections:
                    if session_id in self._connections:
                        self._connections[session_id].discard(ws)
                    self._last_ping.pop(ws, None)
            logger.warning(
                "Cleaned up dead WebSocket connections",
                extra={"session_id": session_id, "count": len(dead_connections)},
            )

    async def cleanup_stale_connections(self) -> None:
        """
        Disconnect clients that haven't sent a ping within the timeout.

        Should be called periodically (e.g., every 30s) from a
        background task.
        """
        now = time.monotonic()
        stale: list[tuple[WebSocket, str]] = []

        async with self._lock:
            for session_id, connections in self._connections.items():
                for ws in connections:
                    last_ping = self._last_ping.get(ws, 0)
                    if now - last_ping > HEARTBEAT_TIMEOUT_SECONDS:
                        stale.append((ws, session_id))

        for ws, session_id in stale:
            try:
                await ws.close(code=1000, reason="Heartbeat timeout")
            except Exception:
                pass
            await self.disconnect(ws, session_id)

        if stale:
            logger.info(
                "Cleaned up stale WebSocket connections",
                extra={"count": len(stale)},
            )

    def clear_session_buffer(self, session_id: str) -> None:
        """Clear the replay buffer for a completed session."""
        self._replay_buffers.pop(session_id, None)


# Module-level singleton
ws_manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """
    WebSocket endpoint handler for real-time session updates.

    Handles:
      - Connection lifecycle (connect, disconnect)
      - Ping/pong heartbeat for stale detection
      - Message replay on reconnection

    Usage from frontend:
      const ws = new WebSocket(`ws://localhost:8000/ws/sessions/${sessionId}`);
      ws.onmessage = (event) => {
        const { event: type, data } = JSON.parse(event.data);
        // Handle task_update, validation, completed events
      };
    """
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Update last-ping timestamp for heartbeat tracking
            ws_manager._last_ping[websocket] = time.monotonic()
            # Echo back as heartbeat acknowledgment
            if data == "ping":
                await websocket.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, session_id)
    except Exception:
        await ws_manager.disconnect(websocket, session_id)
