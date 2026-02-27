"""
Pharma Agentic AI — Supervisor Agent: Grounding Validator.

Validates that every claim in agent results has a corresponding
citation. Detects cross-pillar conflicts. Uses LLM-as-judge
for semantic validation with strict system prompt constraints.

Architecture context:
  - Service: Supervisor Agent (Azure Container App)
  - Responsibility: Citation validation, conflict detection, HITL escalation
  - Upstream: Cosmos DB Change Feed (triggers when all tasks complete)
  - Downstream: Executor Agent (on validation pass), Planner (on re-route)
  - Failure: Flags conflicts as Strategic Risks rather than errors
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from src.shared.config import get_settings
from src.shared.models.enums import ConflictSeverity, PillarType
from src.shared.models.schemas import AgentResult, Citation, ConflictDetail, ValidationResult

logger = logging.getLogger(__name__)

VALIDATION_SYSTEM_PROMPT = """You are the Supervisor Agent for a pharmaceutical intelligence platform.

Your ONLY job is to validate the grounding of agent results.

RULES:
1. Check that EVERY factual claim has a corresponding citation.
2. Check for cross-pillar CONFLICTS (e.g., "market growth" + "blocking patent" = conflict).
3. Output ONLY valid JSON matching the schema below.
4. You MUST NOT generate new data. You are ONLY validating existing data.
5. If data is insufficient, say so. Do NOT fill gaps.

OUTPUT SCHEMA:
{
  "is_valid": true/false,
  "grounding_score": 0.0-1.0,
  "conflicts": [
    {
      "conflict_type": "PATENT_MARKET_CONFLICT",
      "pillars_involved": ["LEGAL", "COMMERCIAL"],
      "description": "string",
      "severity": "LOW|MEDIUM|HIGH|CRITICAL",
      "recommendation": "string"
    }
  ],
  "validation_notes": "string"
}"""


class GroundingValidator:
    """
    Validates agent results for citation grounding and cross-pillar conflicts.

    Uses deterministic rule-based checks first, then LLM-as-judge
    for semantic conflict detection.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._endpoint = settings.openai.endpoint.rstrip("/")
        self._api_key = settings.openai.api_key
        self._deployment = settings.openai.deployment_name
        self._api_version = settings.openai.api_version
        # Connection pool limits prevent unbounded socket creation
        # max_connections=10 is generous for a single Supervisor instance
        self._http_client = httpx.Client(
            timeout=60.0,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
            ),
        )

    def validate(self, agent_results: list[AgentResult]) -> ValidationResult:
        """
        Perform grounding validation and conflict detection.

        Two-pass validation:
          1. Rule-based: Check citation existence for each result
          2. LLM-based: Semantic conflict detection across pillars

        Args:
            agent_results: All agent results for a session.

        Returns:
            ValidationResult with grounding score, conflicts, and notes.
        """
        # ── Pass 1: Rule-based citation check ──────────────
        total_results = len(agent_results)
        grounded_results = sum(1 for r in agent_results if len(r.citations) > 0)
        grounding_score = grounded_results / max(total_results, 1)

        # ── Pass 2: Rule-based conflict detection ──────────
        conflicts = self._detect_rule_based_conflicts(agent_results)

        # ── Pass 3: LLM-based semantic validation ──────────
        try:
            llm_result = self._llm_validation(agent_results)
            if llm_result.get("conflicts"):
                for c in llm_result["conflicts"]:
                    conflicts.append(ConflictDetail(
                        conflict_type=c.get("conflict_type", "UNKNOWN"),
                        pillars_involved=[PillarType(p) for p in c.get("pillars_involved", [])],
                        description=c.get("description", ""),
                        severity=ConflictSeverity(c.get("severity", "MEDIUM")),
                        recommendation=c.get("recommendation", ""),
                    ))

            # Update grounding score from LLM assessment
            llm_grounding = llm_result.get("grounding_score", grounding_score)
            grounding_score = min(grounding_score, llm_grounding)

        except Exception:
            logger.exception("LLM validation failed, using rule-based results only")

        is_valid = grounding_score >= 0.8 and not any(
            c.severity == ConflictSeverity.CRITICAL for c in conflicts
        )

        return ValidationResult(
            is_valid=is_valid,
            conflicts=conflicts,
            grounding_score=grounding_score,
            validation_notes=f"Validated {total_results} results. "
            f"{grounded_results}/{total_results} grounded. "
            f"{len(conflicts)} conflicts detected.",
        )

    def _detect_rule_based_conflicts(
        self,
        results: list[AgentResult],
    ) -> list[ConflictDetail]:
        """Detect conflicts using deterministic business rules."""
        conflicts: list[ConflictDetail] = []

        # Extract pillar findings
        legal_findings = next((r.findings for r in results if r.pillar == PillarType.LEGAL), {})
        commercial_findings = next((r.findings for r in results if r.pillar == PillarType.COMMERCIAL), {})
        clinical_findings = next((r.findings for r in results if r.pillar == PillarType.CLINICAL), {})
        social_findings = next((r.findings for r in results if r.pillar == PillarType.SOCIAL), {})

        # ── Conflict 1: Patent vs Market Entry ─────────────
        blocking_patents = legal_findings.get("blocking_patents", [])
        earliest_entry = legal_findings.get("earliest_generic_entry")
        market_attractiveness = commercial_findings.get("market_attractiveness", "")

        if blocking_patents and market_attractiveness in ("HIGH", "MEDIUM"):
            conflicts.append(ConflictDetail(
                conflict_type="PATENT_MARKET_CONFLICT",
                pillars_involved=[PillarType.LEGAL, PillarType.COMMERCIAL],
                description=(
                    f"Market is {market_attractiveness} attractiveness but "
                    f"{len(blocking_patents)} blocking patent(s) detected. "
                    f"Earliest generic entry: {earliest_entry or 'Unknown'}."
                ),
                severity=ConflictSeverity.CRITICAL,
                recommendation="Delay market entry until patent expiry or seek license.",
            ))

        # ── Conflict 2: High Competition + Safety Risk ─────
        saturation = clinical_findings.get("competitive_saturation", "")
        risk_level = social_findings.get("regulatory_risk", "")

        if saturation == "HIGH" and risk_level in ("HIGH", "CRITICAL"):
            conflicts.append(ConflictDetail(
                conflict_type="COMPETITION_SAFETY_CONFLICT",
                pillars_involved=[PillarType.CLINICAL, PillarType.SOCIAL],
                description=(
                    f"High competitive saturation ({clinical_findings.get('total_active_trial_count', 0)} active trials) "
                    f"combined with {risk_level} safety risk signals."
                ),
                severity=ConflictSeverity.HIGH,
                recommendation="Re-evaluate risk/reward. Consider differentiated formulation.",
            ))

        # ── Conflict 3: Strong Market + No Data ────────────
        if market_attractiveness == "HIGH" and not clinical_findings.get("active_trials"):
            conflicts.append(ConflictDetail(
                conflict_type="DATA_GAP",
                pillars_involved=[PillarType.COMMERCIAL, PillarType.CLINICAL],
                description="High market potential but no clinical trial data available.",
                severity=ConflictSeverity.MEDIUM,
                recommendation="Conduct deeper clinical landscape analysis.",
            ))

        return conflicts

    def _llm_validation(self, results: list[AgentResult]) -> dict[str, Any]:
        """Use LLM-as-judge for semantic validation."""
        summary = []
        for r in results:
            summary.append({
                "pillar": r.pillar.value,
                "confidence": r.confidence,
                "citation_count": len(r.citations),
                "key_findings": {k: v for k, v in r.findings.items() if k not in ("adverse_events",)},
            })

        url = (
            f"{self._endpoint}/openai/deployments/{self._deployment}"
            f"/chat/completions?api-version={self._api_version}"
        )

        response = self._http_client.post(
            url,
            headers={"Content-Type": "application/json", "api-key": self._api_key},
            json={
                "messages": [
                    {"role": "system", "content": VALIDATION_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(summary, default=str)},
                ],
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
                "max_tokens": 1500,
            },
        )
        response.raise_for_status()
        response_json = response.json()

        # Track token usage for cost telemetry
        usage = response_json.get("usage", {})
        if usage:
            logger.info(
                "LLM validation token usage",
                extra={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "model": self._deployment,
                },
            )

        content = response_json["choices"][0]["message"]["content"]
        return json.loads(content)

    def close(self) -> None:
        self._http_client.close()
