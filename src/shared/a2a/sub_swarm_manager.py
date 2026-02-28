"""
Pharma Agentic AI — A2A Sub-Swarm Manager.

Enables dynamic agent sub-swarming: parent agents can spawn child
agents via Kafka/A2A protocol. Manages the fan-out/fan-in lifecycle.

Architecture context:
  - Service: Shared A2A infrastructure
  - Responsibility: Parent-child task orchestration
  - Upstream: Retriever agents (spawn sub-tasks for deep analysis)
  - Downstream: Kafka (publish child tasks), A2A Registry (discover agents)
  - Constraints: Max depth 3, timeout 120s per swarm

Example:
  ClinicalRetriever finds 10 trials → spawns 10 DataExtractionAgents
  → waits for all reports → merges into unified clinical analysis.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Safety limits
MAX_SWARM_DEPTH = 3
SWARM_TIMEOUT_SECONDS = 120.0
MAX_CHILDREN_PER_PARENT = 20


class SwarmStatus(StrEnum):
    """Lifecycle states for a sub-swarm."""
    PENDING = "PENDING"
    SPAWNING = "SPAWNING"
    WAITING = "WAITING"
    MERGING = "MERGING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class ChildTask(BaseModel):
    """A spawned child task within a sub-swarm."""
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    status: SwarmStatus = SwarmStatus.PENDING
    result: dict[str, Any] | None = None
    spawned_at: float = Field(default_factory=time.time)


class SubSwarm(BaseModel):
    """
    Represents a fan-out/fan-in swarm unit.

    A parent agent creates a SubSwarm with N child tasks.
    The manager tracks completion and merges results.
    """
    swarm_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_session_id: str
    parent_agent_type: str
    depth: int = 0
    status: SwarmStatus = SwarmStatus.PENDING
    children: list[ChildTask] = Field(default_factory=list)
    merged_result: dict[str, Any] | None = None
    created_at: float = Field(default_factory=time.time)


class SubSwarmManager:
    """
    Manages dynamic agent sub-swarming with fan-out/fan-in.

    Lifecycle:
      1. Parent calls `create_swarm()` with child task specs
      2. Manager validates depth limit and spawns children via broker
      3. Parent calls `wait_for_completion()` (async, with timeout)
      4. As child results arrive, `report_child_result()` is called
      5. On all children complete, `merge_results()` aggregates data
      6. Parent receives merged result

    Safety:
      - Max depth: 3 (prevents infinite recursion)
      - Max children: 20 per parent
      - Timeout: 120s per swarm
    """

    def __init__(self) -> None:
        self._swarms: dict[str, SubSwarm] = {}
        self._completion_events: dict[str, asyncio.Event] = {}

    def create_swarm(
        self,
        parent_session_id: str,
        parent_agent_type: str,
        child_specs: list[dict[str, Any]],
        current_depth: int = 0,
    ) -> SubSwarm:
        """
        Create a new sub-swarm with child task specifications.

        Args:
            parent_session_id: Session ID of the parent.
            parent_agent_type: Agent type of the parent.
            child_specs: List of dicts with 'agent_type' and 'payload' keys.
            current_depth: Current recursion depth (0 = top level).

        Returns:
            SubSwarm instance.

        Raises:
            ValueError: If depth limit or child count limit exceeded.
        """
        if current_depth >= MAX_SWARM_DEPTH:
            raise ValueError(
                f"Sub-swarm depth limit exceeded: {current_depth} >= {MAX_SWARM_DEPTH}. "
                "This prevents infinite recursion."
            )

        if len(child_specs) > MAX_CHILDREN_PER_PARENT:
            raise ValueError(
                f"Too many children ({len(child_specs)}) — max {MAX_CHILDREN_PER_PARENT}. "
                "Consider batching or reducing parallelism."
            )

        children = [
            ChildTask(
                agent_type=spec.get("agent_type", ""),
                payload=spec.get("payload", {}),
            )
            for spec in child_specs
        ]

        swarm = SubSwarm(
            parent_session_id=parent_session_id,
            parent_agent_type=parent_agent_type,
            depth=current_depth,
            children=children,
        )

        self._swarms[swarm.swarm_id] = swarm
        self._completion_events[swarm.swarm_id] = asyncio.Event()

        logger.info(
            "Sub-swarm created",
            extra={
                "swarm_id": swarm.swarm_id,
                "parent": parent_agent_type,
                "children": len(children),
                "depth": current_depth,
            },
        )
        return swarm

    def report_child_result(
        self,
        swarm_id: str,
        task_id: str,
        result: dict[str, Any],
    ) -> bool:
        """
        Report a child task's result.

        Returns True if ALL children are now complete (triggers merge).
        """
        swarm = self._swarms.get(swarm_id)
        if not swarm:
            logger.warning("Result for unknown swarm", extra={"swarm_id": swarm_id})
            return False

        for child in swarm.children:
            if child.task_id == task_id:
                child.status = SwarmStatus.COMPLETED
                child.result = result
                break

        # Check if all children complete
        all_done = all(c.status in (SwarmStatus.COMPLETED, SwarmStatus.FAILED) for c in swarm.children)

        if all_done:
            swarm.status = SwarmStatus.MERGING
            swarm.merged_result = self._merge_results(swarm)
            swarm.status = SwarmStatus.COMPLETED
            event = self._completion_events.get(swarm_id)
            if event:
                event.set()
            logger.info("Sub-swarm completed", extra={"swarm_id": swarm_id})
            return True

        return False

    async def wait_for_completion(self, swarm_id: str) -> dict[str, Any]:
        """
        Wait for all children to complete (with timeout).

        Returns merged result dict, or raises TimeoutError.
        """
        event = self._completion_events.get(swarm_id)
        if not event:
            raise ValueError(f"Unknown swarm ID: {swarm_id}")

        try:
            await asyncio.wait_for(event.wait(), timeout=SWARM_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            swarm = self._swarms[swarm_id]
            swarm.status = SwarmStatus.TIMEOUT
            logger.error("Sub-swarm timed out", extra={"swarm_id": swarm_id})
            # Return partial results from completed children
            return self._merge_results(swarm)

        swarm = self._swarms[swarm_id]
        return swarm.merged_result or {}

    def _merge_results(self, swarm: SubSwarm) -> dict[str, Any]:
        """
        Merge all child results into a single aggregated dict.

        Completed children contribute their results.
        Failed/timed-out children are logged as errors.
        """
        merged: dict[str, Any] = {
            "swarm_id": swarm.swarm_id,
            "parent_agent": swarm.parent_agent_type,
            "total_children": len(swarm.children),
            "completed": 0,
            "failed": 0,
            "child_results": [],
            "errors": [],
        }

        for child in swarm.children:
            if child.status == SwarmStatus.COMPLETED and child.result:
                merged["completed"] += 1
                merged["child_results"].append({
                    "task_id": child.task_id,
                    "agent_type": child.agent_type,
                    "result": child.result,
                })
            else:
                merged["failed"] += 1
                merged["errors"].append({
                    "task_id": child.task_id,
                    "agent_type": child.agent_type,
                    "status": child.status.value,
                })

        return merged

    def cleanup_swarm(self, swarm_id: str) -> None:
        """Remove a completed swarm from memory."""
        self._swarms.pop(swarm_id, None)
        self._completion_events.pop(swarm_id, None)
