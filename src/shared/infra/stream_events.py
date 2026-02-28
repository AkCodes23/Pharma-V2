"""
Pharma Agentic AI — WebSocket Streaming Events.

Typed event classes for real-time agent progress streaming
via WebSocket. Enables ChatGPT-like UX where users see each
agent working in real time.

Architecture context:
  - Service: Shared infrastructure
  - Responsibility: Typed event contracts for WS streaming
  - Upstream: All agents publish events via Redis Pub/Sub
  - Downstream: WebSocket ConnectionManager → frontend

Event flow:
  Agent → Redis PUBLISH → ConnectionManager subscriber → WebSocket → Frontend
"""

from __future__ import annotations

import json
import logging
import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class StreamEventType(StrEnum):
    """Event types for the WebSocket stream."""

    AGENT_STARTED = "agent_started"
    AGENT_PROGRESS = "agent_progress"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    VALIDATION_STARTED = "validation_started"
    VALIDATION_RESULT = "validation_result"
    REPORT_GENERATING = "report_generating"
    REPORT_READY = "report_ready"
    SESSION_COMPLETED = "session_completed"
    SESSION_FAILED = "session_failed"


class StreamEvent(BaseModel):
    """
    Base WebSocket streaming event.

    All events carry a timestamp, session context, and
    human-readable message for the frontend to display.
    """

    event_type: StreamEventType
    session_id: str
    timestamp: float = Field(default_factory=time.time)
    agent_type: str = ""
    pillar: str = ""
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


# ── Convenience Constructors ──────────────────────────────


def agent_started(session_id: str, agent_type: str, pillar: str) -> StreamEvent:
    """Create an event when an agent begins processing a task."""
    return StreamEvent(
        event_type=StreamEventType.AGENT_STARTED,
        session_id=session_id,
        agent_type=agent_type,
        pillar=pillar,
        message=f"{agent_type} is searching {pillar.lower()} data sources...",
    )


def agent_progress(
    session_id: str,
    agent_type: str,
    pillar: str,
    message: str,
    progress_data: dict[str, Any] | None = None,
) -> StreamEvent:
    """Create a progress update event (e.g., 'Found 3 patents...')."""
    return StreamEvent(
        event_type=StreamEventType.AGENT_PROGRESS,
        session_id=session_id,
        agent_type=agent_type,
        pillar=pillar,
        message=message,
        data=progress_data or {},
    )


def agent_completed(
    session_id: str,
    agent_type: str,
    pillar: str,
    result_summary: str,
    grounding_score: float = 0.0,
) -> StreamEvent:
    """Create an event when an agent finishes successfully."""
    return StreamEvent(
        event_type=StreamEventType.AGENT_COMPLETED,
        session_id=session_id,
        agent_type=agent_type,
        pillar=pillar,
        message=f"{agent_type} completed ({pillar}): {result_summary}",
        data={"grounding_score": grounding_score},
    )


def agent_failed(
    session_id: str,
    agent_type: str,
    pillar: str,
    error: str,
) -> StreamEvent:
    """Create an event when an agent fails."""
    return StreamEvent(
        event_type=StreamEventType.AGENT_FAILED,
        session_id=session_id,
        agent_type=agent_type,
        pillar=pillar,
        message=f"{agent_type} failed ({pillar}): {error}",
        data={"error": error},
    )


def validation_result(
    session_id: str,
    pillar: str,
    score: float,
    passed: bool,
) -> StreamEvent:
    """Create an event after grounding validation completes."""
    status = "✅ passed" if passed else "❌ failed"
    return StreamEvent(
        event_type=StreamEventType.VALIDATION_RESULT,
        session_id=session_id,
        pillar=pillar,
        message=f"Validation {status} for {pillar} (score: {score:.2f})",
        data={"score": score, "passed": passed},
    )


def report_ready(session_id: str, report_url: str) -> StreamEvent:
    """Create an event when the final PDF report is ready."""
    return StreamEvent(
        event_type=StreamEventType.REPORT_READY,
        session_id=session_id,
        message="📄 Your report is ready for download.",
        data={"report_url": report_url},
    )


def session_completed(session_id: str, decision: str) -> StreamEvent:
    """Create a terminal event when the full session completes."""
    return StreamEvent(
        event_type=StreamEventType.SESSION_COMPLETED,
        session_id=session_id,
        message=f"Session complete — Decision: {decision}",
        data={"decision": decision},
    )


# ── Redis Pub/Sub Bridge ──────────────────────────────────

WS_CHANNEL_PREFIX = "pharma:ws:"


def publish_stream_event(redis_client: Any, event: StreamEvent) -> None:
    """
    Publish a streaming event via Redis Pub/Sub.

    Any service can call this to push events to all connected
    WebSocket clients watching this session.

    Args:
        redis_client: A redis.Redis instance.
        event: The StreamEvent to publish.
    """
    channel = f"{WS_CHANNEL_PREFIX}{event.session_id}"
    payload = event.model_dump_json()
    try:
        redis_client.publish(channel, payload)
    except Exception:
        logger.debug("Failed to publish stream event", extra={"session_id": event.session_id})
