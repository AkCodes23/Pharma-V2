"""
Pharma Agentic AI — Executor Agent: Main Service.

Triggered by the Supervisor on validation pass. Aggregates all
validated agent results, generates the executive report, creates
visual charts, renders the PDF, and uploads to Blob Storage.

Architecture context:
  - Service: Executor Agent (Azure Container App)
  - Responsibility: Final synthesis → PDF/Excel artifacts
  - Upstream: Supervisor Agent
  - Downstream: Blob Storage, API Gateway
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.infra.audit import AuditService
from src.shared.infra.cosmos_client import CosmosDBClient
from src.shared.models.enums import AgentType, AuditAction, PillarType, SessionStatus
from src.shared.models.schemas import Session

from src.agents.executor.chart_generator import (
    generate_patent_timeline,
    generate_revenue_chart,
    generate_safety_gauge,
)
from src.agents.executor.pdf_engine import PDFEngine
from src.agents.executor.report_generator import ReportGenerator

logger = logging.getLogger(__name__)


class ExecutorAgent:
    """
    Executor Agent — final synthesis and artifact generation.

    Lifecycle:
      1. Receive validated session from Supervisor
      2. Generate executive report (Context-Constrained Decoding)
      3. Generate visual charts (matplotlib)
      4. Create PDF artifact
      5. Upload to Blob Storage
      6. Mark session as COMPLETED
    """

    def __init__(
        self,
        cosmos: CosmosDBClient,
        audit: AuditService,
    ) -> None:
        self._cosmos = cosmos
        self._audit = audit
        self._report_gen = ReportGenerator()
        self._pdf_engine = PDFEngine()

    def execute(self, session_id: str) -> dict[str, Any]:
        """
        Generate the final executive report and artifacts.

        Args:
            session_id: The validated session to synthesize.

        Returns:
            Dict with decision, report_url, and artifacts.
        """
        session = self._cosmos.get_session(session_id)

        # Update status
        self._cosmos.update_session_status(session_id, SessionStatus.SYNTHESIZING)

        # 1. Generate text report
        report_markdown, decision, rationale = self._report_gen.generate_report(session)

        # 2. Generate charts
        charts = self._generate_charts(session)

        # 3. Embed charts into report
        if charts:
            report_markdown += "\n\n## Visual Analytics\n\n"
            for chart_name, chart_b64 in charts.items():
                if chart_b64:
                    report_markdown += f"### {chart_name}\n"
                    report_markdown += f"![{chart_name}](data:image/png;base64,{chart_b64})\n\n"

        # 4. For MVP, we store the report as markdown in the session
        # In production, this generates a PDF via WeasyPrint and uploads to Blob Storage
        report_url = f"/api/v1/sessions/{session_id}/report"

        # 5. Generate PDF and upload to Blob Storage
        try:
            all_citations = []
            for result in session.agent_results:
                all_citations.extend([
                    {"source_name": c.source_name, "source_url": c.source_url, "retrieved_at": c.retrieved_at, "data_hash": c.data_hash}
                    for c in result.citations
                ])

            pdf_bytes = self._pdf_engine.render_pdf(
                report_markdown=report_markdown,
                session_id=session_id,
                query=session.query,
                decision=decision.value,
                citations=all_citations,
            )
            if pdf_bytes:
                blob_url = self._pdf_engine.upload_to_blob(pdf_bytes, session_id)
                report_url = blob_url
        except Exception:
            logger.exception("PDF generation failed — using markdown fallback")

        # 6. Complete the session
        self._cosmos.complete_session(
            session_id=session_id,
            decision=decision.value,
            rationale=rationale,
            report_url=report_url,
        )

        # 6. Audit
        self._audit.log(
            session_id=session_id,
            user_id=session.user_id,
            agent_type=AgentType.EXECUTOR,
            action=AuditAction.REPORT_GENERATED,
            payload={
                "decision": decision.value,
                "rationale": rationale,
                "report_length": len(report_markdown),
                "chart_count": len(charts),
            },
        )

        self._audit.log(
            session_id=session_id,
            user_id=session.user_id,
            agent_type=AgentType.EXECUTOR,
            action=AuditAction.SESSION_COMPLETED,
            payload={"final_decision": decision.value},
        )

        logger.info(
            "Execution completed",
            extra={
                "session_id": session_id,
                "decision": decision.value,
            },
        )

        return {
            "session_id": session_id,
            "decision": decision.value,
            "rationale": rationale,
            "report_url": report_url,
            "report_markdown": report_markdown,
            "charts": list(charts.keys()),
        }

    def _generate_charts(self, session: Session) -> dict[str, str]:
        """Generate visual chart artifacts from agent results."""
        charts: dict[str, str] = {}

        for result in session.agent_results:
            try:
                if result.pillar == PillarType.COMMERCIAL:
                    revenue_data = result.findings.get("revenue_data", {})
                    if revenue_data:
                        charts["Revenue Trend"] = generate_revenue_chart(revenue_data)

                elif result.pillar == PillarType.LEGAL:
                    charts["Patent Timeline"] = generate_patent_timeline(result.findings)

                elif result.pillar == PillarType.SOCIAL:
                    charts["Safety Risk Assessment"] = generate_safety_gauge(result.findings)

            except Exception:
                logger.exception(
                    "Chart generation failed",
                    extra={"pillar": result.pillar.value},
                )

        return {k: v for k, v in charts.items() if v}  # Remove empties

    def close(self) -> None:
        self._report_gen.close()
        # PDFEngine has no persistent connections to close
