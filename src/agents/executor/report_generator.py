"""
Pharma Agentic AI — Executor Agent: Report Generator.

Generates executive reports using Context-Constrained Decoding.
The system prompt is hardcoded to use ONLY provided JSON context.
Every claim MUST end with a citation block.

Architecture context:
  - Service: Executor Agent
  - Responsibility: Aggregate validated results → executive report
  - Upstream: Supervisor Agent (validated results)
  - Downstream: Blob Storage (PDF/Excel), API Gateway (response)
  - Key constraint: ZERO parametric memory usage — output constrained to retrieved context
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from src.shared.config import get_settings
from src.shared.models.enums import ConflictSeverity, DecisionOutcome, PillarType
from src.shared.models.schemas import AgentResult, ConflictDetail, Session, ValidationResult

logger = logging.getLogger(__name__)

# ── Context-Constrained System Prompt (Hardcoded) ──────────
REPORT_SYSTEM_PROMPT = """You are the Executor Agent for a pharmaceutical strategic intelligence platform.

ABSOLUTE RULES — VIOLATION OF THESE RULES IS FORBIDDEN:
1. You may ONLY answer using the provided JSON context. 
2. If the answer is not in the context, output "INSUFFICIENT DATA" for that section.
3. Every factual claim MUST end with a citation block: [Source: <source_name>, Retrieved: <timestamp>]
4. You must NEVER generate facts, dates, numbers, or statistics from your own knowledge.
5. You must structure the report in the format below.
6. If conflicts exist, they MUST be prominently displayed as "STRATEGIC RISKS".

REPORT FORMAT:
# Executive Strategic Assessment
## Query Summary
## Decision: GO / NO-GO / CONDITIONAL GO
## Decision Rationale
## Legal Analysis (Patent Landscape)
## Clinical Analysis (Trial Pipeline)
## Commercial Analysis (Market Opportunity)
## Safety Analysis (Adverse Events)
## Strategic Risks & Conflicts
## Recommendations
## Citation Registry (All Sources)"""


class ReportGenerator:
    """
    Generates executive reports using Context-Constrained Decoding.

    The LLM's output is mathematically constrained to the provided
    JSON context from validated agent results. No parametric memory.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._endpoint = settings.openai.endpoint.rstrip("/")
        self._api_key = settings.openai.api_key
        self._deployment = settings.openai.deployment_name
        self._api_version = settings.openai.api_version
        # Connection pool limits: report generation can be slow (120s timeout)
        # but we still need bounded resource usage
        self._http_client = httpx.Client(
            timeout=120.0,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
            ),
        )

    def generate_report(self, session: Session) -> tuple[str, DecisionOutcome, str]:
        """
        Generate an executive report from validated session data.

        Args:
            session: The fully populated Session with agent results and validation.

        Returns:
            Tuple of (markdown_report, decision, rationale).
        """
        # Build the context payload (ONLY source for the LLM)
        context = self._build_context(session)

        url = (
            f"{self._endpoint}/openai/deployments/{self._deployment}"
            f"/chat/completions?api-version={self._api_version}"
        )

        response = self._http_client.post(
            url,
            headers={"Content-Type": "application/json", "api-key": self._api_key},
            json={
                "messages": [
                    {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(context, default=str)},
                ],
                "temperature": 0.0,
                "max_tokens": 4000,
            },
        )
        response.raise_for_status()
        response_json = response.json()

        # Track token usage for cost telemetry dashboard
        usage = response_json.get("usage", {})
        if usage:
            logger.info(
                "Report generation token usage",
                extra={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "model": self._deployment,
                    "session_id": session.id,
                },
            )

        report_markdown = response_json["choices"][0]["message"]["content"]

        # Determine decision from the analysis
        decision, rationale = self._determine_decision(session)

        logger.info(
            "Report generated",
            extra={
                "session_id": session.id,
                "decision": decision.value,
                "report_length": len(report_markdown),
            },
        )

        return report_markdown, decision, rationale

    def _build_context(self, session: Session) -> dict[str, Any]:
        """Build the constrained context payload for the LLM."""
        context: dict[str, Any] = {
            "query": session.query,
            "parameters": session.parameters.model_dump(),
            "pillar_results": {},
        }

        for result in session.agent_results:
            pillar_key = result.pillar.value.lower()
            context["pillar_results"][pillar_key] = {
                "findings": result.findings,
                "confidence": result.confidence,
                "citation_count": len(result.citations),
                "citations": [
                    {
                        "source": c.source_name,
                        "url": c.source_url,
                        "retrieved_at": c.retrieved_at.isoformat(),
                        "data_hash": c.data_hash,
                        "excerpt": c.excerpt,
                    }
                    for c in result.citations
                ],
            }

        if session.validation:
            context["validation"] = {
                "is_valid": session.validation.is_valid,
                "grounding_score": session.validation.grounding_score,
                "conflicts": [
                    {
                        "type": c.conflict_type,
                        "severity": c.severity.value,
                        "description": c.description,
                        "recommendation": c.recommendation,
                    }
                    for c in session.validation.conflicts
                ],
            }

        return context

    def _determine_decision(
        self, session: Session
    ) -> tuple[DecisionOutcome, str]:
        """
        Determine the GO/NO-GO decision based on structured analysis.

        This is a deterministic rule-based decision — NOT LLM-generated.
        """
        if not session.validation:
            return DecisionOutcome.INSUFFICIENT_DATA, "Validation not completed."

        conflicts = session.validation.conflicts
        critical_conflicts = [c for c in conflicts if c.severity == ConflictSeverity.CRITICAL]
        high_conflicts = [c for c in conflicts if c.severity == ConflictSeverity.HIGH]

        # Extract key metrics
        legal_result = next(
            (r for r in session.agent_results if r.pillar == PillarType.LEGAL), None
        )
        commercial_result = next(
            (r for r in session.agent_results if r.pillar == PillarType.COMMERCIAL), None
        )

        blocking_patents = []
        if legal_result:
            blocking_patents = legal_result.findings.get("blocking_patents", [])

        market_attractiveness = ""
        if commercial_result:
            market_attractiveness = commercial_result.findings.get("market_attractiveness", "")

        # Decision rules
        if critical_conflicts:
            reasons = "; ".join(c.description for c in critical_conflicts)
            return DecisionOutcome.NO_GO, f"Critical conflicts detected: {reasons}"

        if blocking_patents and not critical_conflicts:
            earliest = legal_result.findings.get("earliest_generic_entry") if legal_result else "Unknown"
            return (
                DecisionOutcome.CONDITIONAL_GO,
                f"Blocking patents exist (expiry: {earliest}). "
                f"Market entry conditional on patent expiration or licensing.",
            )

        if high_conflicts:
            return (
                DecisionOutcome.CONDITIONAL_GO,
                f"{len(high_conflicts)} high-severity risk(s) identified. Proceed with caution.",
            )

        if market_attractiveness in ("HIGH", "MEDIUM") and not blocking_patents:
            return DecisionOutcome.GO, "No blocking patents. Favorable market conditions."

        if session.validation.grounding_score < 0.5:
            return (
                DecisionOutcome.INSUFFICIENT_DATA,
                f"Grounding score too low ({session.validation.grounding_score:.0%}). "
                "Insufficient data for confident decision.",
            )

        return DecisionOutcome.CONDITIONAL_GO, "Mixed signals. Further analysis recommended."

    def close(self) -> None:
        self._http_client.close()
