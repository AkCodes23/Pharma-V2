"""
Pharma Agentic AI — Celery Tasks: PDF Generation.

Offloads PDF rendering from the Executor Agent hot path to
a background Celery worker.

Architecture context:
  - Queue: pharma.pdf
  - Responsibility: WeasyPrint PDF rendering + Blob Storage upload
  - Upstream: Executor Agent (dispatches after report generation)
  - Downstream: Azure Blob Storage (PDF artifacts)
  - Time limit: 5 min soft, 10 min hard
"""

from __future__ import annotations

import logging

from src.shared.infra.celery_app import app

logger = logging.getLogger(__name__)


@app.task(
    name="src.shared.tasks.pdf_task.generate_pdf",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="pharma.pdf",
    acks_late=True,
)
def generate_pdf(
    self,
    session_id: str,
    report_markdown: str,
    query: str,
    decision: str,
    citations: list[dict],
) -> dict:
    """
    Generate a PDF report and upload to Blob Storage.

    Args:
        session_id: Session UUID.
        report_markdown: Markdown report content.
        query: Original user query.
        decision: GO/NO-GO decision.
        citations: List of citation dicts.

    Returns:
        Dict with blob_url and file_size_bytes.
    """
    try:
        from src.agents.executor.pdf_engine import PDFEngine

        engine = PDFEngine()
        pdf_bytes = engine.render_pdf(
            report_markdown=report_markdown,
            session_id=session_id,
            query=query,
            decision=decision,
            citations=citations,
        )

        if not pdf_bytes:
            logger.warning("PDF generation returned empty bytes", extra={"session_id": session_id})
            return {"blob_url": None, "file_size_bytes": 0}

        blob_url = engine.upload_to_blob(pdf_bytes, session_id)

        logger.info(
            "PDF generated via Celery",
            extra={
                "session_id": session_id,
                "file_size_bytes": len(pdf_bytes),
                "blob_url": blob_url,
            },
        )

        return {
            "blob_url": blob_url,
            "file_size_bytes": len(pdf_bytes),
            "session_id": session_id,
        }

    except Exception as exc:
        logger.exception("PDF generation failed", extra={"session_id": session_id})
        raise self.retry(exc=exc)
