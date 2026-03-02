"""
Pharma Agentic AI — WebSocket Connection Manager.

Handles real-time session updates from the backend to the
frontend dashboard via WebSocket connections.

Architecture context:
  - Service: Shared infrastructure (used by Planner Agent)
  - Responsibility: Real-time UI updates for session progress
  - Upstream: Agent pipeline (broadcasts events on status change)
  - Downstream: Frontend WebSocket clients (local) or Azure Web PubSub (prod)
  - Scaling: Local = in-memory per instance; Azure = Web PubSub managed
  - Failure: Graceful degradation; frontend falls back to polling

Backends:
  - Local: In-memory ConnectionManager + Redis Pub/Sub fan-out
  - Azure: Web PubSub (WEB_PUBSUB_USE_AZURE=true)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Protocol

from fastapi import WebSocket, WebSocketDisconnect

from src.shared.config import get_settings

logger = logging.getLogger(__name__)

# Max events to buffer per session for replay on reconnection
REPLAY_BUFFER_SIZE = 20
# Seconds of silence before a client is considered stale
HEARTBEAT_TIMEOUT_SECONDS = 60.0
REDIS_POLL_TIMEOUT_SECONDS = 1.0
STALE_CLEANUP_INTERVAL_SECONDS = 15.0


class PushManager(Protocol):
    """Protocol for WebSocket/PubSub push backends."""

    async def broadcast(self, session_id: str, event: str, data: dict[str, Any]) -> None: ...
    async def connect(self, websocket: WebSocket, session_id: str) -> None: ...
    async def disconnect(self, websocket: WebSocket, session_id: str) -> None: ...


# ── Local WebSocket Manager ───────────────────────────────


class ConnectionManager:
    """
    In-memory WebSocket manager for local/dev environments.

    Features:
      - Multi-client: Multiple frontend tabs can watch the same session
      - Heartbeat timeout: Disconnects clients that haven't pinged in 60s
      - Message replay: Stores last N events per session for reconnection
      - Dead connection cleanup: Automatic on broadcast failure
      - Redis Pub/Sub: Receives events from any service via Redis channels

    Thread-safety: Uses asyncio.Lock for connection set mutations.
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._last_ping: dict[WebSocket, float] = {}
        self._replay_buffers: dict[str, deque[str]] = {}
        self._lock = asyncio.Lock()
        self._pubsub_task: asyncio.Task | None = None
        self._stale_cleanup_task: asyncio.Task | None = None
        self._redis_client: Any | None = None
        self._pubsub: Any | None = None

    async def start_redis_subscriber(self) -> None:
        """
        Start a non-blocking background task for Redis Pub/Sub.

        Pattern: pharma:ws:* — matches all session channels.
        """
        if self._pubsub_task and not self._pubsub_task.done():
            return

        try:
            from src.shared.infra.redis_client import RedisClient

            self._redis_client = RedisClient()
            self._pubsub = self._redis_client.client.pubsub()
            self._pubsub.psubscribe("pharma:ws:*")

            async def _poll_loop() -> None:
                loop = asyncio.get_running_loop()
                try:
                    while True:
                        pubsub = self._pubsub
                        if pubsub is None:
                            break

                        msg = await loop.run_in_executor(
                            None,
                            lambda: pubsub.get_message(
                                ignore_subscribe_messages=True,
                                timeout=REDIS_POLL_TIMEOUT_SECONDS,
                            ),
                        )
                        if not msg or msg.get("type") != "pmessage":
                            continue

                        channel = msg["channel"]
                        if isinstance(channel, bytes):
                            channel = channel.decode()
                        session_id = channel.replace("pharma:ws:", "")
                        data = msg["data"]
                        if isinstance(data, bytes):
                            data = data.decode()
                        await self.broadcast_raw(session_id, data)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Redis WebSocket subscriber loop failed")

            self._pubsub_task = asyncio.create_task(_poll_loop())
            logger.info("Redis Pub/Sub subscriber started for WS streaming")

        except Exception:
            logger.warning("Redis Pub/Sub subscriber failed to start — streaming disabled")

    async def stop_redis_subscriber(self) -> None:
        """Stop Redis Pub/Sub background processing and close connections."""
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
            self._pubsub_task = None

        if self._pubsub is not None:
            try:
                self._pubsub.close()
            except Exception:
                logger.debug("Failed to close Redis pubsub", exc_info=True)
            self._pubsub = None

        if self._redis_client is not None:
            try:
                self._redis_client.close()
            except Exception:
                logger.debug("Failed to close Redis client", exc_info=True)
            self._redis_client = None

    async def start_stale_cleanup_loop(self) -> None:
        """Start periodic stale WebSocket connection cleanup."""
        if self._stale_cleanup_task and not self._stale_cleanup_task.done():
            return

        async def _cleanup_loop() -> None:
            try:
                while True:
                    await asyncio.sleep(STALE_CLEANUP_INTERVAL_SECONDS)
                    await self.cleanup_stale_connections()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Stale WebSocket cleanup loop failed")

        self._stale_cleanup_task = asyncio.create_task(_cleanup_loop())
        logger.info(
            "WebSocket stale-connection cleanup loop started",
            extra={"interval_s": STALE_CLEANUP_INTERVAL_SECONDS},
        )

    async def stop_stale_cleanup_loop(self) -> None:
        """Stop periodic stale WebSocket connection cleanup."""
        if self._stale_cleanup_task:
            self._stale_cleanup_task.cancel()
            try:
                await self._stale_cleanup_task
            except asyncio.CancelledError:
                pass
            self._stale_cleanup_task = None

    async def start_background_tasks(self) -> None:
        """Start all local WebSocket background tasks."""
        await self.start_redis_subscriber()
        await self.start_stale_cleanup_loop()

    async def stop_background_tasks(self) -> None:
        """Stop all local WebSocket background tasks."""
        await self.stop_stale_cleanup_loop()
        await self.stop_redis_subscriber()

    async def broadcast_raw(self, session_id: str, raw_message: str) -> None:
        """Broadcast a pre-serialized message to all clients watching a session."""
        async with self._lock:
            if session_id not in self._replay_buffers:
                self._replay_buffers[session_id] = deque(maxlen=REPLAY_BUFFER_SIZE)
            self._replay_buffers[session_id].append(raw_message)
            connections = self._connections.get(session_id, set()).copy()

        dead: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_text(raw_message)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    if session_id in self._connections:
                        self._connections[session_id].discard(ws)
                    self._last_ping.pop(ws, None)

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Accept a WebSocket connection and register it for a session."""
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
        """Remove a WebSocket connection from a session group."""
        async with self._lock:
            if session_id in self._connections:
                self._connections[session_id].discard(websocket)
                if not self._connections[session_id]:
                    del self._connections[session_id]
            self._last_ping.pop(websocket, None)

        logger.info("WebSocket client disconnected", extra={"session_id": session_id})

    async def broadcast(self, session_id: str, event: str, data: dict[str, Any]) -> None:
        """Send an event to all clients watching a session."""
        message = json.dumps({"event": event, "data": data}, default=str)

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
        """Disconnect clients that haven't sent a ping within the timeout."""
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
            logger.info("Cleaned up stale WebSocket connections", extra={"count": len(stale)})

    def clear_session_buffer(self, session_id: str) -> None:
        """Clear the replay buffer for a completed session."""
        self._replay_buffers.pop(session_id, None)


# ── Azure Web PubSub Manager ─────────────────────────────


class WebPubSubManager:
    """
    Azure Web PubSub manager for production environments.

    Clients connect directly to the Web PubSub endpoint.
    Server sends events via the Web PubSub REST API.

    No in-memory connection state is needed — PubSub handles
    connection tracking, fan-out, and replay.

    Usage:
      1. Client calls GET /ws/negotiate to get PubSub token + URL
      2. Client opens WebSocket to Web PubSub endpoint directly
      3. Server broadcasts via REST API (this class)
    """

    def __init__(self) -> None:
        self._service_client = None
        self._hub_name = "pharma-sessions"

    def _ensure_client(self) -> None:
        """Lazy-initialize the Web PubSub service client."""
        if self._service_client is not None:
            return

        settings = get_settings()
        pubsub_cfg = settings.web_pubsub
        if not pubsub_cfg.connection_string:
            logger.warning("Web PubSub connection string not configured")
            return

        try:
            from azure.messaging.webpubsubservice import WebPubSubServiceClient

            self._service_client = WebPubSubServiceClient.from_connection_string(
                connection_string=pubsub_cfg.connection_string,
                hub=pubsub_cfg.hub_name,
            )
            self._hub_name = pubsub_cfg.hub_name
            logger.info("Azure Web PubSub client initialized", extra={"hub": self._hub_name})
        except Exception as e:
            logger.warning("Web PubSub init failed", extra={"error": str(e)})

    async def broadcast(self, session_id: str, event: str, data: dict[str, Any]) -> None:
        """
        Broadcast an event to all clients in a session group.

        Uses Web PubSub group messaging — clients join a group
        named after their session_id when they connect.
        """
        self._ensure_client()
        if self._service_client is None:
            return

        message = json.dumps({"event": event, "data": data}, default=str)

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._service_client.send_to_group(
                    group=session_id,
                    message=message,
                    content_type="application/json",
                ),
            )
        except Exception as e:
            logger.warning(
                "Web PubSub broadcast failed",
                extra={"session_id": session_id, "event": event, "error": str(e)},
            )

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """
        Not used for Web PubSub — clients connect directly to PubSub endpoint.

        This method exists to satisfy the PushManager protocol but is
        a no-op. Use get_client_token() instead.
        """
        logger.debug("WebPubSubManager.connect called — clients use PubSub endpoint directly")

    async def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        """No-op — PubSub handles disconnection lifecycle."""
        pass

    async def start_background_tasks(self) -> None:
        """No-op for Azure Web PubSub mode."""
        return

    async def stop_background_tasks(self) -> None:
        """No-op for Azure Web PubSub mode."""
        return

    def get_client_token(self, session_id: str, user_id: str = "") -> dict[str, str]:
        """
        Generate a client access token for WebSocket connection.

        Returns:
            Dict with 'url' (WebSocket endpoint) and 'token' (access token).
        """
        self._ensure_client()
        if self._service_client is None:
            return {"url": "", "token": "", "error": "Web PubSub not configured"}

        try:
            token = self._service_client.get_client_access_token(
                user_id=user_id or f"user-{session_id}",
                groups=[session_id],
                roles=["webpubsub.joinLeaveGroup", "webpubsub.sendToGroup"],
            )
            return {"url": token["url"], "token": token.get("token", "")}
        except Exception as e:
            logger.warning("Failed to generate PubSub token", extra={"error": str(e)})
            return {"url": "", "token": "", "error": str(e)}


# ── Factory + Singleton ───────────────────────────────────


def _create_push_manager() -> ConnectionManager | WebPubSubManager:
    """Create the appropriate push manager based on configuration."""
    try:
        settings = get_settings()
        if hasattr(settings, "web_pubsub") and settings.web_pubsub.use_azure:
            logger.info("Using Azure Web PubSub for real-time push")
            return WebPubSubManager()
    except Exception:
        pass

    logger.info("Using local WebSocket connection manager")
    return ConnectionManager()


# Module-level singleton — selected based on WEB_PUBSUB_USE_AZURE flag
ws_manager = _create_push_manager()


async def start_websocket_manager() -> None:
    """Start WS manager background tasks (if any)."""
    await ws_manager.start_background_tasks()


async def stop_websocket_manager() -> None:
    """Stop WS manager background tasks (if any)."""
    await ws_manager.stop_background_tasks()


async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """
    WebSocket endpoint handler for real-time session updates (local mode).

    In Azure Web PubSub mode, clients connect directly to the PubSub
    endpoint. This handler is only used in local development.

    Usage from frontend:
      const ws = new WebSocket(`ws://localhost:8000/ws/sessions/${sessionId}`);
      ws.onmessage = (event) => {
        const { event: type, data } = JSON.parse(event.data);
        // Handle task_update, validation, completed events
      };
    """
    if isinstance(ws_manager, WebPubSubManager):
        # In PubSub mode, return the PubSub connection info instead
        await websocket.accept()
        token_info = ws_manager.get_client_token(session_id)
        await websocket.send_text(json.dumps({"event": "redirect", "data": token_info}))
        await websocket.close()
        return

    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Update last-ping timestamp for heartbeat tracking
            if isinstance(ws_manager, ConnectionManager):
                async with ws_manager._lock:
                    ws_manager._last_ping[websocket] = time.monotonic()
            # Echo back as heartbeat acknowledgment
            if data == "ping":
                await websocket.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, session_id)
    except Exception:
        await ws_manager.disconnect(websocket, session_id)
