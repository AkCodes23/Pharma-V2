from __future__ import annotations

from collections import defaultdict

from src.demo.fixture_loader import get_fixture_loader
from src.shared.models.enums import ConflictSeverity, DecisionOutcome
from src.shared.models.schemas import Session
from src.shared.ports.report_engine import ReportEngine


class FixtureReportGenerator(ReportEngine):
    """Deterministic report synthesis for offline standalone-demo mode."""

    def generate_report(self, session: Session) -> tuple[str, DecisionOutcome, str]:
        decision, rationale = self._determine_decision(session)
        template = get_fixture_loader().render_report_template()

        findings_by_pillar: dict[str, list[str]] = defaultdict(list)
        for result in session.agent_results:
            findings_by_pillar[result.pillar.value].append(
                ", ".join(sorted(result.findings.keys())[:6]) or "no findings"
            )

        section_lines: list[str] = []
        for pillar in sorted(findings_by_pillar.keys()):
            summary = "; ".join(findings_by_pillar[pillar])
            section_lines.append(f"## {pillar} Findings")
            section_lines.append(summary)
            section_lines.append("")

        markdown = template.format(
            query=session.query,
            decision=decision.value,
            rationale=rationale,
            findings="\n".join(section_lines).strip(),
        )
        return markdown, decision, rationale

    def _determine_decision(self, session: Session) -> tuple[DecisionOutcome, str]:
        validation = session.validation
        if validation and any(c.severity == ConflictSeverity.CRITICAL for c in validation.conflicts):
            return DecisionOutcome.NO_GO, "Critical conflict found during validation."

        for result in session.agent_results:
            if result.pillar.value == "LEGAL":
                blockers = result.findings.get("blocking_patents", [])
                if blockers:
                    return (
                        DecisionOutcome.CONDITIONAL_GO,
                        "Blocking patents exist. Proceed conditionally after legal mitigation.",
                    )

        if validation and validation.grounding_score < 0.5:
            return DecisionOutcome.INSUFFICIENT_DATA, "Grounding score too low for confident decision."

        return DecisionOutcome.GO, "No critical blockers detected in deterministic demo analysis."

    def close(self) -> None:
        return
