"""
Executor agent service.

Synthesizes validated results into final report artifacts.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException

from src.agents.executor.chart_generator import (
    generate_patent_timeline,
    generate_revenue_chart,
    generate_safety_gauge,
)
from src.agents.executor.pdf_engine import PDFEngine
from src.agents.executor.report_generator import ReportGenerator
from src.shared.bootstrap import bootstrap_agent
from src.shared.infra.audit import AuditService
from src.shared.infra.auth import require_internal_api_key
from src.shared.infra.cosmos_client import CosmosDBClient
from src.shared.models.enums import AgentType, AuditAction, PillarType, SessionStatus
from src.shared.models.schemas import Session

logger = logging.getLogger(__name__)


class ExecutorAgent:
    """Final synthesis and artifact generation."""

    def __init__(self, cosmos: CosmosDBClient, audit: AuditService) -> None:
        self._cosmos = cosmos
        self._audit = audit
        self._report_gen = ReportGenerator()
        self._pdf_engine = PDFEngine()

    def execute(self, session_id: str) -> dict[str, Any]:
        """Generate final report artifacts for a session."""
        session = self._cosmos.get_session(session_id)
        self._cosmos.update_session_status(session_id, SessionStatus.SYNTHESIZING)

        report_markdown, decision, rationale = self._report_gen.generate_report(session)
        charts = self._generate_charts(session)

        if charts:
            report_markdown += "\n\n## Visual Analytics\n\n"
            for chart_name, chart_b64 in charts.items():
                if chart_b64:
                    report_markdown += f"### {chart_name}\n"
                    report_markdown += f"![{chart_name}](data:image/png;base64,{chart_b64})\n\n"

        report_url = f"/api/v1/sessions/{session_id}/report"

        try:
            all_citations = []
            for result in session.agent_results:
                all_citations.extend([
                    {
                        "source_name": c.source_name,
                        "source_url": c.source_url,
                        "retrieved_at": c.retrieved_at,
                        "data_hash": c.data_hash,
                    }
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
                report_url = self._pdf_engine.upload_to_blob(pdf_bytes, session_id)
        except Exception:
            logger.exception("PDF generation failed; using markdown fallback")

        self._cosmos.complete_session(
            session_id=session_id,
            decision=decision.value,
            rationale=rationale,
            report_url=report_url,
        )

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

        return {
            "session_id": session_id,
            "decision": decision.value,
            "rationale": rationale,
            "report_url": report_url,
            "report_markdown": report_markdown,
            "charts": list(charts.keys()),
        }

    def _generate_charts(self, session: Session) -> dict[str, str]:
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
                logger.exception("Chart generation failed", extra={"pillar": result.pillar.value})
        return {k: v for k, v in charts.items() if v}

    def close(self) -> None:
        self._report_gen.close()


_cosmos: CosmosDBClient | None = None
_audit: AuditService | None = None
_executor: ExecutorAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cosmos, _audit, _executor

    bootstrap_agent(agent_name="executor-agent")
    _cosmos = CosmosDBClient()
    _cosmos.ensure_containers()
    _audit = AuditService(_cosmos)
    _executor = ExecutorAgent(_cosmos, _audit)

    logger.info("Executor Agent started")
    yield

    if _executor:
        _executor.close()
    if _audit:
        _audit.shutdown()
    logger.info("Executor Agent stopped")


app = FastAPI(
    title="Pharma Agentic AI - Executor Agent",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "executor-agent"}


@app.post("/api/v1/sessions/{session_id}/execute")
async def execute_session(
    session_id: str,
    _: None = Depends(require_internal_api_key),
) -> dict[str, Any]:
    if _executor is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    try:
        return _executor.execute(session_id)
    except Exception as exc:
        logger.exception("Execution failed", extra={"session_id": session_id})
        raise HTTPException(status_code=500, detail=f"Execution failed: {type(exc).__name__}") from exc


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8002")))
