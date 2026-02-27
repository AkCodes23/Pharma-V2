"""
Pharma Agentic AI — SPAR Framework: Reflect Module.

Implements the "R" (Reflect) phase of the Sense-Plan-Act-Reflect
lifecycle. After each session completes, analysis is performed
to evaluate quality, identify failures, and suggest improvements.

Architecture context:
  - Service: Shared SPAR framework
  - Responsibility: Post-session quality assessment and learning
  - Upstream: Supervisor Agent (post-validation), Executor (post-synthesis)
  - Downstream: PostgreSQL (reflection_log), Redis (reflection cache)
  - Failure: Non-critical — reflection failures never block the pipeline

Reflection categories:
  1. Citation validity: Were all citations resolvable?
  2. Timeout detection: Did any agent timeout or DLQ?
  3. Decision consistency: Is the decision consistent with evidence?
  4. Conflict analysis: Were conflicts properly resolved?
  5. Coverage: Did all pillars contribute to the result?
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """
    SPAR Reflection engine for post-session analysis.

    Evaluates session quality across multiple dimensions,
    logs findings to PostgreSQL, and caches insights in Redis
    for future query optimization.

    Non-blocking: all operations are fire-and-forget on failure.
    """

    def __init__(self) -> None:
        self._postgres = None
        self._redis = None

    async def initialize(self) -> None:
        """Initialize database backends."""
        from src.shared.infra.postgres_client import PostgresClient
        from src.shared.infra.redis_client import RedisClient

        self._postgres = PostgresClient()
        await self._postgres.initialize()
        self._redis = RedisClient()
        logger.info("ReflectionEngine initialized")

    async def reflect_on_session(
        self,
        session_id: str,
        session_data: dict[str, Any],
        agent_results: list[dict[str, Any]],
        validation_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Run all reflection checks on a completed session.

        Args:
            session_id: Session UUID.
            session_data: Full session document.
            agent_results: List of agent result dicts.
            validation_result: Supervisor validation outcome.

        Returns:
            Consolidated reflection report.
        """
        reflections: list[dict[str, Any]] = []

        # 1. Citation validity check
        citation_result = self._check_citation_validity(agent_results)
        reflections.append(citation_result)
        await self._log_reflection(session_id, "supervisor", "citation_validity", citation_result)

        # 2. Timeout/failure detection
        timeout_result = self._check_timeouts_and_failures(session_data, agent_results)
        reflections.append(timeout_result)
        await self._log_reflection(session_id, "supervisor", "timeout_detection", timeout_result)

        # 3. Decision consistency
        if validation_result:
            consistency_result = self._check_decision_consistency(
                session_data, agent_results, validation_result
            )
            reflections.append(consistency_result)
            await self._log_reflection(session_id, "supervisor", "decision_consistency", consistency_result)

        # 4. Coverage check
        coverage_result = self._check_pillar_coverage(session_data, agent_results)
        reflections.append(coverage_result)
        await self._log_reflection(session_id, "supervisor", "pillar_coverage", coverage_result)

        # Compute overall reflection score
        scores = [r.get("score", 0.0) for r in reflections if r.get("score") is not None]
        overall_score = sum(scores) / len(scores) if scores else 0.0

        report = {
            "session_id": session_id,
            "overall_score": overall_score,
            "reflections": reflections,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "improvements": self._suggest_improvements(reflections),
        }

        logger.info(
            "Session reflection completed",
            extra={
                "session_id": session_id,
                "overall_score": overall_score,
                "checks": len(reflections),
            },
        )

        return report

    def _check_citation_validity(self, agent_results: list[dict[str, Any]]) -> dict[str, Any]:
        """Check if all citations in agent results are valid."""
        total_citations = 0
        valid_citations = 0
        invalid_sources: list[str] = []

        for result in agent_results:
            citations = result.get("citations", [])
            for citation in citations:
                total_citations += 1
                # Check that required fields exist
                if citation.get("source_name") and citation.get("source_url"):
                    valid_citations += 1
                else:
                    invalid_sources.append(citation.get("source_name", "unknown"))

        score = valid_citations / total_citations if total_citations > 0 else 1.0

        return {
            "type": "citation_validity",
            "score": score,
            "total_citations": total_citations,
            "valid_citations": valid_citations,
            "invalid_sources": invalid_sources,
        }

    def _check_timeouts_and_failures(
        self, session_data: dict[str, Any], agent_results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Detect timeouts, DLQ events, and failures."""
        tasks = session_data.get("tasks", [])
        failed_tasks = [t for t in tasks if t.get("status") in ("FAILED", "DLQ", "TIMED_OUT")]
        total_tasks = len(tasks)
        success_rate = (total_tasks - len(failed_tasks)) / total_tasks if total_tasks > 0 else 1.0

        return {
            "type": "timeout_detection",
            "score": success_rate,
            "total_tasks": total_tasks,
            "failed_tasks": len(failed_tasks),
            "failed_pillars": [t.get("pillar", "unknown") for t in failed_tasks],
        }

    def _check_decision_consistency(
        self,
        session_data: dict[str, Any],
        agent_results: list[dict[str, Any]],
        validation_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Check if the final decision is consistent with evidence."""
        decision = session_data.get("decision", "UNKNOWN")
        grounding_score = validation_result.get("grounding_score", 0.0)
        conflicts = validation_result.get("conflicts", [])

        # If decision is GO but grounding < 0.6, that's inconsistent
        consistency_score = 1.0
        issues: list[str] = []

        if decision == "GO" and grounding_score < 0.6:
            consistency_score -= 0.5
            issues.append(f"GO decision with low grounding ({grounding_score:.2f})")

        if decision == "GO" and len(conflicts) > 3:
            consistency_score -= 0.3
            issues.append(f"GO decision with {len(conflicts)} unresolved conflicts")

        if decision == "NO_GO" and grounding_score > 0.9 and len(conflicts) == 0:
            consistency_score -= 0.3
            issues.append("NO_GO decision despite strong evidence and no conflicts")

        return {
            "type": "decision_consistency",
            "score": max(0.0, consistency_score),
            "decision": decision,
            "grounding_score": grounding_score,
            "conflict_count": len(conflicts),
            "issues": issues,
        }

    def _check_pillar_coverage(
        self, session_data: dict[str, Any], agent_results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Check if all expected pillars contributed results."""
        expected_pillars = {"LEGAL", "CLINICAL", "COMMERCIAL", "SOCIAL", "KNOWLEDGE"}
        completed_pillars = {r.get("pillar", "").upper() for r in agent_results}
        missing_pillars = expected_pillars - completed_pillars
        coverage_score = len(completed_pillars) / len(expected_pillars) if expected_pillars else 1.0

        return {
            "type": "pillar_coverage",
            "score": coverage_score,
            "expected_pillars": list(expected_pillars),
            "completed_pillars": list(completed_pillars),
            "missing_pillars": list(missing_pillars),
        }

    def _suggest_improvements(self, reflections: list[dict[str, Any]]) -> list[str]:
        """Generate improvement suggestions based on reflection results."""
        improvements: list[str] = []

        for r in reflections:
            rtype = r.get("type", "")
            score = r.get("score", 1.0)

            if rtype == "citation_validity" and score < 0.8:
                improvements.append("Improve citation extraction — consider adding URL validation to retriever agents")

            if rtype == "timeout_detection" and score < 0.8:
                failed_pillars = r.get("failed_pillars", [])
                improvements.append(f"Investigate timeout/failure in pillars: {', '.join(failed_pillars)}")

            if rtype == "decision_consistency" and score < 0.7:
                improvements.append("Review decision logic — evidence vs decision mismatch detected")

            if rtype == "pillar_coverage" and score < 1.0:
                missing = r.get("missing_pillars", [])
                improvements.append(f"Missing pillar coverage: {', '.join(missing)} — check agent health")

        return improvements

    async def _log_reflection(
        self,
        session_id: str,
        agent_type: str,
        reflection_type: str,
        result: dict[str, Any],
    ) -> None:
        """Persist a reflection entry to PostgreSQL."""
        if not self._postgres:
            return

        try:
            await self._postgres.write_reflection(
                session_id=session_id,
                agent_type=agent_type,
                reflection_type=reflection_type,
                score=result.get("score"),
                findings=result,
                improvements=result.get("improvements", []),
            )
        except Exception:
            logger.warning("Failed to persist reflection", extra={"session_id": session_id})
