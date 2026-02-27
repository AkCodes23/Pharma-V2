"""
Pharma Agentic AI — Short-Term Memory (Redis-Backed).

Provides conversation context for multi-turn queries within a
session. Enables the Planner to reference prior user interactions.

Architecture context:
  - Service: Shared memory layer (Context Engineering)
  - Responsibility: Session-scoped conversation history
  - Backend: Redis with session TTL
  - Data ownership: Ephemeral — TTL-based auto-expiry
  - Failure: Graceful — missing history doesn't break workflow
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ShortTermMemory:
    """
    Redis-backed conversation context for multi-turn sessions.

    Stores the last N messages exchanged with a user during a session.
    Auto-expires with the session TTL (10 min default).

    Used by the Planner Agent to:
      - Reference prior clarification answers
      - Refine queries based on conversation history
      - Provide continuity for follow-up questions
    """

    def __init__(self) -> None:
        self._redis = None

    def initialize(self) -> None:
        """Initialize Redis backend."""
        from src.shared.infra.redis_client import RedisClient
        self._redis = RedisClient()
        logger.info("ShortTermMemory initialized")

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """
        Add a message to the session conversation history.

        Args:
            session_id: Session UUID.
            role: Message role ('user', 'assistant', 'system').
            content: Message content.
        """
        if not self._redis:
            return

        messages = self._redis.get_short_term_memory(session_id)
        messages.append({"role": role, "content": content})

        # Keep only last 20 messages to bound memory
        max_messages = 20
        if len(messages) > max_messages:
            messages = messages[-max_messages:]

        self._redis.store_short_term_memory(session_id, messages)

    def get_context(self, session_id: str) -> list[dict[str, Any]]:
        """
        Retrieve conversation context for a session.

        Returns:
            List of message dicts with 'role' and 'content'.
        """
        if not self._redis:
            return []
        return self._redis.get_short_term_memory(session_id)

    def get_formatted_context(self, session_id: str) -> str:
        """
        Get conversation history formatted for LLM prompt injection.

        Returns a string like:
            User: What about Keytruda?
            Assistant: Keytruda is a PD-1 inhibitor...
        """
        messages = self.get_context(session_id)
        if not messages:
            return ""
        return "\n".join(
            f"{msg['role'].capitalize()}: {msg['content']}" for msg in messages
        )

    def clear(self, session_id: str) -> None:
        """Clear conversation history for a session."""
        if self._redis:
            self._redis.client.delete(f"memory:short:{session_id}")
