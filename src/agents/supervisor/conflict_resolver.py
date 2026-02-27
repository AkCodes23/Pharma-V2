"""
Pharma Agentic AI — Supervisor: Conflict Resolver.

Handles cross-pillar conflicts detected by the validator.
Routes conflicts to one of three paths:
  1. AUTO-RESOLVE: Deterministic resolution via business rules
  2. ANNOTATE: Flag as Strategic Risk (surfaced in report)
  3. ESCALATE: Trigger HITL via webhook (Teams Adaptive Card)

Architecture context:
  - Service: Supervisor Agent (sub-component)
  - Responsibility: Conflict triage and resolution
  - Upstream: GroundingValidator
  - Downstream: Executor (annotations), Teams webhook (escalation)
"""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from typing import Any

import httpx

from src.shared.models.enums import ConflictSeverity
from src.shared.models.schemas import ConflictDetail

logger = logging.getLogger(__name__)


class ResolutionAction(StrEnum):
    """How a conflict is resolved."""
    AUTO_RESOLVED = "AUTO_RESOLVED"
    ANNOTATED = "ANNOTATED"
    ESCALATED = "ESCALATED"


class ConflictResolution:
    """Result of conflict resolution."""

    def __init__(
        self,
        conflict: ConflictDetail,
        action: ResolutionAction,
        annotation: str | None = None,
        escalation_ticket_id: str | None = None,
    ) -> None:
        self.conflict = conflict
        self.action = action
        self.annotation = annotation
        self.escalation_ticket_id = escalation_ticket_id


class ConflictResolver:
    """
    Triages and resolves cross-pillar conflicts.

    Resolution strategy by severity:
      - LOW: Auto-resolve with standard annotation
      - MEDIUM: Annotate as Strategic Risk in report
      - HIGH: Annotate + optional escalation
      - CRITICAL: Mandatory HITL escalation via Teams webhook
    """

    def __init__(self, teams_webhook_url: str | None = None) -> None:
        self._teams_webhook_url = teams_webhook_url
        self._http = httpx.Client(timeout=15.0)

    def resolve(self, conflicts: list[ConflictDetail]) -> list[ConflictResolution]:
        """
        Process all conflicts and determine resolution actions.

        Args:
            conflicts: List of detected conflicts.

        Returns:
            List of ConflictResolution objects with actions.
        """
        resolutions: list[ConflictResolution] = []

        for conflict in conflicts:
            resolution = self._triage(conflict)
            resolutions.append(resolution)

            logger.info(
                "Conflict resolved",
                extra={
                    "conflict_type": conflict.conflict_type,
                    "severity": conflict.severity.value,
                    "action": resolution.action.value,
                },
            )

        return resolutions

    def _triage(self, conflict: ConflictDetail) -> ConflictResolution:
        """Route conflict to appropriate resolution path."""
        if conflict.severity == ConflictSeverity.LOW:
            return self._auto_resolve(conflict)
        elif conflict.severity == ConflictSeverity.MEDIUM:
            return self._annotate(conflict)
        elif conflict.severity == ConflictSeverity.HIGH:
            return self._annotate_with_warning(conflict)
        else:  # CRITICAL
            return self._escalate(conflict)

    def _auto_resolve(self, conflict: ConflictDetail) -> ConflictResolution:
        """Low-severity: resolve with standard annotation."""
        annotation = (
            f"⚠️ Minor data inconsistency detected between "
            f"{', '.join(p.value for p in conflict.pillars_involved)}. "
            f"Impact: {conflict.description}. "
            f"Action: {conflict.recommendation}"
        )
        return ConflictResolution(
            conflict=conflict,
            action=ResolutionAction.AUTO_RESOLVED,
            annotation=annotation,
        )

    def _annotate(self, conflict: ConflictDetail) -> ConflictResolution:
        """Medium-severity: flag as Strategic Risk in report."""
        annotation = (
            f"🔶 STRATEGIC RISK — {conflict.conflict_type.replace('_', ' ')}\n"
            f"Pillars: {', '.join(p.value for p in conflict.pillars_involved)}\n"
            f"Finding: {conflict.description}\n"
            f"Recommendation: {conflict.recommendation}"
        )
        return ConflictResolution(
            conflict=conflict,
            action=ResolutionAction.ANNOTATED,
            annotation=annotation,
        )

    def _annotate_with_warning(self, conflict: ConflictDetail) -> ConflictResolution:
        """High-severity: annotate + attempt escalation."""
        annotation = (
            f"🔴 HIGH-SEVERITY RISK — {conflict.conflict_type.replace('_', ' ')}\n"
            f"Pillars: {', '.join(p.value for p in conflict.pillars_involved)}\n"
            f"Finding: {conflict.description}\n"
            f"Recommendation: {conflict.recommendation}\n"
            f"⚠️ This conflict may require human review."
        )

        # Attempt escalation if webhook configured
        ticket_id = None
        if self._teams_webhook_url:
            ticket_id = self._send_teams_card(conflict)

        return ConflictResolution(
            conflict=conflict,
            action=ResolutionAction.ANNOTATED if not ticket_id else ResolutionAction.ESCALATED,
            annotation=annotation,
            escalation_ticket_id=ticket_id,
        )

    def _escalate(self, conflict: ConflictDetail) -> ConflictResolution:
        """Critical: mandatory HITL escalation via Teams webhook."""
        annotation = (
            f"🚨 CRITICAL CONFLICT — HUMAN REVIEW REQUIRED\n"
            f"Type: {conflict.conflict_type.replace('_', ' ')}\n"
            f"Pillars: {', '.join(p.value for p in conflict.pillars_involved)}\n"
            f"Finding: {conflict.description}\n"
            f"Recommendation: {conflict.recommendation}"
        )

        ticket_id = None
        if self._teams_webhook_url:
            ticket_id = self._send_teams_card(conflict)
        else:
            logger.warning(
                "No Teams webhook configured for CRITICAL conflict escalation",
                extra={"conflict_type": conflict.conflict_type},
            )

        return ConflictResolution(
            conflict=conflict,
            action=ResolutionAction.ESCALATED,
            annotation=annotation,
            escalation_ticket_id=ticket_id,
        )

    def _send_teams_card(self, conflict: ConflictDetail) -> str | None:
        """
        Send a Microsoft Teams Adaptive Card for HITL escalation.

        Returns the message ID if successful, None otherwise.
        """
        if not self._teams_webhook_url:
            return None

        severity_color = {
            ConflictSeverity.LOW: "good",
            ConflictSeverity.MEDIUM: "warning",
            ConflictSeverity.HIGH: "attention",
            ConflictSeverity.CRITICAL: "attention",
        }

        card_payload = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": "🚨 Pharma AI — Conflict Escalation",
                            "weight": "Bolder",
                            "size": "Large",
                            "color": severity_color.get(conflict.severity, "default"),
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Type", "value": conflict.conflict_type.replace("_", " ")},
                                {"title": "Severity", "value": conflict.severity.value},
                                {"title": "Pillars", "value": ", ".join(p.value for p in conflict.pillars_involved)},
                            ],
                        },
                        {
                            "type": "TextBlock",
                            "text": conflict.description,
                            "wrap": True,
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**Recommendation:** {conflict.recommendation}",
                            "wrap": True,
                            "color": "warning",
                        },
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "Review in Dashboard",
                            "url": "https://pharma-ai.example.com/admin/conflicts",
                        },
                    ],
                },
            }],
        }

        try:
            response = self._http.post(
                self._teams_webhook_url,
                json=card_payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            logger.info("Teams escalation sent", extra={"severity": conflict.severity.value})
            return response.text[:32]  # Use first 32 chars as ticket ID
        except Exception:
            logger.exception("Failed to send Teams escalation")
            return None

    def close(self) -> None:
        self._http.close()
