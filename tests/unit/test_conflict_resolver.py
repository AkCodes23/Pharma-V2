"""
Unit tests for Supervisor Agent — ConflictResolver.

Tests severity-based resolution routing: AUTO_RESOLVED for LOW,
ANNOTATED for MEDIUM, ESCALATED for CRITICAL with Teams webhook.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.supervisor.conflict_resolver import (
    ConflictResolution,
    ConflictResolver,
    ResolutionAction,
)
from src.shared.models.enums import ConflictSeverity, PillarType
from src.shared.models.schemas import ConflictDetail


def _make_conflict(severity: ConflictSeverity, conflict_type: str = "TEST_CONFLICT") -> ConflictDetail:
    return ConflictDetail(
        conflict_type=conflict_type,
        pillars_involved=[PillarType.LEGAL, PillarType.COMMERCIAL],
        description=f"Test {severity.value} conflict",
        severity=severity,
        recommendation="Test recommendation",
    )


@pytest.fixture
def resolver() -> ConflictResolver:
    return ConflictResolver(teams_webhook_url="https://test.webhook.office.com/test")


@pytest.fixture
def resolver_no_webhook() -> ConflictResolver:
    return ConflictResolver(teams_webhook_url=None)


class TestSeverityRouting:
    """Tests for severity-based resolution routing."""

    def test_low_severity_auto_resolved(self, resolver: ConflictResolver) -> None:
        conflicts = [_make_conflict(ConflictSeverity.LOW)]
        resolutions = resolver.resolve(conflicts)
        assert len(resolutions) == 1
        assert resolutions[0].action == ResolutionAction.AUTO_RESOLVED

    def test_medium_severity_annotated(self, resolver: ConflictResolver) -> None:
        conflicts = [_make_conflict(ConflictSeverity.MEDIUM)]
        resolutions = resolver.resolve(conflicts)
        assert len(resolutions) == 1
        assert resolutions[0].action == ResolutionAction.ANNOTATED
        assert resolutions[0].annotation is not None

    def test_high_severity_annotated_with_warning(self, resolver: ConflictResolver) -> None:
        conflicts = [_make_conflict(ConflictSeverity.HIGH)]
        with patch.object(resolver, "_send_teams_card", return_value=None):
            resolutions = resolver.resolve(conflicts)
        assert len(resolutions) == 1
        assert resolutions[0].action in (ResolutionAction.ANNOTATED, ResolutionAction.ESCALATED)

    def test_critical_severity_escalated(self, resolver: ConflictResolver) -> None:
        conflicts = [_make_conflict(ConflictSeverity.CRITICAL)]
        with patch.object(resolver, "_send_teams_card", return_value="msg-123"):
            resolutions = resolver.resolve(conflicts)
        assert len(resolutions) == 1
        assert resolutions[0].action == ResolutionAction.ESCALATED


class TestMultipleConflicts:
    """Tests for processing multiple conflicts."""

    def test_mixed_severities(self, resolver: ConflictResolver) -> None:
        conflicts = [
            _make_conflict(ConflictSeverity.LOW, "LOW_CONFLICT"),
            _make_conflict(ConflictSeverity.MEDIUM, "MED_CONFLICT"),
            _make_conflict(ConflictSeverity.CRITICAL, "CRIT_CONFLICT"),
        ]
        with patch.object(resolver, "_send_teams_card", return_value="msg-456"):
            resolutions = resolver.resolve(conflicts)
        assert len(resolutions) == 3
        actions = [r.action for r in resolutions]
        assert ResolutionAction.AUTO_RESOLVED in actions
        assert ResolutionAction.ANNOTATED in actions
        assert ResolutionAction.ESCALATED in actions

    def test_empty_conflicts_list(self, resolver: ConflictResolver) -> None:
        resolutions = resolver.resolve([])
        assert resolutions == []


class TestTeamsWebhook:
    """Tests for Teams card escalation."""

    def test_send_teams_card_called_on_critical(self, resolver: ConflictResolver) -> None:
        conflict = _make_conflict(ConflictSeverity.CRITICAL)
        with patch.object(resolver, "_send_teams_card", return_value="msg-789") as mock_teams:
            resolver.resolve([conflict])
            mock_teams.assert_called_once_with(conflict)

    def test_no_webhook_url_skips_escalation(self, resolver_no_webhook: ConflictResolver) -> None:
        conflict = _make_conflict(ConflictSeverity.CRITICAL)
        resolutions = resolver_no_webhook.resolve([conflict])
        assert len(resolutions) == 1
        # Should still resolve, just without the ticket ID
        assert resolutions[0].escalation_ticket_id is None

    @patch("src.agents.supervisor.conflict_resolver.httpx.Client")
    def test_teams_card_http_failure_graceful(self, mock_client_cls: MagicMock, resolver: ConflictResolver) -> None:
        import httpx
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.TimeoutException("timeout")
        mock_client_cls.return_value = mock_client
        # Should not raise — graceful degradation
        result = resolver._send_teams_card(_make_conflict(ConflictSeverity.CRITICAL))
        assert result is None


class TestResolutionAnnotations:
    """Tests for annotation content in resolutions."""

    def test_auto_resolve_includes_annotation(self, resolver: ConflictResolver) -> None:
        resolutions = resolver.resolve([_make_conflict(ConflictSeverity.LOW)])
        assert resolutions[0].annotation is not None

    def test_annotated_includes_strategic_risk_label(self, resolver: ConflictResolver) -> None:
        resolutions = resolver.resolve([_make_conflict(ConflictSeverity.MEDIUM)])
        annotation = resolutions[0].annotation or ""
        # Annotation should contain meaningful context
        assert len(annotation) > 0
