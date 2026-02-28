"""
Pharma Agentic AI — Celery RAG Ingestion Tasks.

Background Celery tasks that ingest documents into Azure AI Search
after each retriever agent fetches data from external APIs.

Architecture context:
  - Service: Celery worker (pharma.rag queue)
  - Responsibility: Background async document ingestion into RAG pipeline
  - Upstream: Retriever agents (triggered after API calls)
  - Downstream: IngestionPipeline → EmbeddingService → AI Search
  - Failure: Retry 3× with exponential backoff; DLQ after exhaustion
  - Cost awareness: Embeddings are charged — deduplicate before queuing

Task catalogue:
  1. ingest_fda_document       — FDA OpenFDA API response → LEGAL index
  2. ingest_clinical_trial     — ClinicalTrials.gov study → CLINICAL index
  3. ingest_news_article       — Tavily news result → NEWS index
  4. ingest_session_findings   — Completed session output → pillar index

All tasks are:
  - Idempotent (same source_id → upsert, not duplicate)
  - Self-contained (no shared mutable state)
  - Observable (structured logs with task_id, source_id, timing)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


def _run_async(coro) -> Any:
    """Run an async coroutine from Celery's sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Task 1: FDA document ingestion ────────────────────────

@shared_task(
    name="pharma.rag.ingest_fda_document",
    queue="pharma.rag",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,
    reject_on_worker_lost=True,
)
def ingest_fda_document(
    self,
    fda_data: dict[str, Any],
    drug_name: str,
    session_id: str = "",
) -> dict[str, Any]:
    """
    Ingest an FDA OpenFDA API response into the LEGAL pillar index.

    Called by the legal retriever after each FDA API query.
    Idempotent: SHA-256 source ID prevents duplicates on re-query.

    Args:
        fda_data: Raw FDA API result dict.
        drug_name: Normalized drug name for metadata filtering.
        session_id: Source session UUID.

    Returns:
        Dict with chunks_upserted, source_id, latency_ms.
    """
    from src.shared.rag.ingestion_pipeline import IngestionPipeline, from_fda_response

    start = time.perf_counter()
    try:
        doc = from_fda_response(fda_data, drug_name, session_id)
        if not doc:
            logger.info("FDA response produced no content — skipping",
                        extra={"drug_name": drug_name, "task_id": self.request.id})
            return {"chunks_upserted": 0, "skipped": True}

        pipeline = IngestionPipeline()
        count = _run_async(pipeline.ingest_document(doc))
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        logger.info(
            "FDA document ingested",
            extra={"drug_name": drug_name, "source_id": doc.source_id,
                   "chunks": count, "latency_ms": elapsed_ms, "task_id": self.request.id},
        )
        return {"chunks_upserted": count, "source_id": doc.source_id, "latency_ms": elapsed_ms}

    except Exception as exc:
        logger.error("FDA ingest failed", extra={"error": str(exc), "task_id": self.request.id})
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 5)


# ── Task 2: Clinical trial ingestion ─────────────────────

@shared_task(
    name="pharma.rag.ingest_clinical_trial",
    queue="pharma.rag",
    bind=True,
    max_retries=3,
    default_retry_delay=15,
    acks_late=True,
    reject_on_worker_lost=True,
)
def ingest_clinical_trial(
    self,
    trial_data: dict[str, Any],
    drug_name: str,
    session_id: str = "",
) -> dict[str, Any]:
    """
    Ingest a ClinicalTrials.gov study into the CLINICAL pillar index.

    Called by the clinical retriever after each trial search.

    Args:
        trial_data: Raw ClinicalTrials.gov study dict (API v2 format).
        drug_name: Normalized drug name.
        session_id: Source session UUID.
    """
    from src.shared.rag.ingestion_pipeline import IngestionPipeline, from_clinical_trial

    start = time.perf_counter()
    try:
        doc = from_clinical_trial(trial_data, drug_name, session_id)
        if not doc:
            return {"chunks_upserted": 0, "skipped": True}

        pipeline = IngestionPipeline()
        count = _run_async(pipeline.ingest_document(doc))
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        logger.info(
            "Clinical trial ingested",
            extra={"drug_name": drug_name, "source_id": doc.source_id,
                   "chunks": count, "latency_ms": elapsed_ms},
        )
        return {"chunks_upserted": count, "source_id": doc.source_id, "latency_ms": elapsed_ms}

    except Exception as exc:
        logger.error("Clinical ingest failed", extra={"error": str(exc)})
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 5)


# ── Task 3: News article ingestion ────────────────────────

@shared_task(
    name="pharma.rag.ingest_news_article",
    queue="pharma.rag",
    bind=True,
    max_retries=2,
    default_retry_delay=5,
    acks_late=True,
)
def ingest_news_article(
    self,
    article: dict[str, Any],
    drug_name: str,
    session_id: str = "",
) -> dict[str, Any]:
    """
    Ingest a Tavily news article into the NEWS pillar index.

    Called by the news retriever after web search.
    Short retry (2×) since news articles change rapidly.

    Args:
        article: Tavily search result dict (url, title, content, score).
        drug_name: Normalized drug name.
        session_id: Source session UUID.
    """
    from src.shared.rag.ingestion_pipeline import IngestionPipeline, from_news_article

    start = time.perf_counter()
    try:
        doc = from_news_article(article, drug_name, session_id)
        if not doc:
            return {"chunks_upserted": 0, "skipped": True}

        pipeline = IngestionPipeline()
        count = _run_async(pipeline.ingest_document(doc))
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        return {"chunks_upserted": count, "source_id": doc.source_id, "latency_ms": elapsed_ms}

    except Exception as exc:
        logger.error("News ingest failed", extra={"error": str(exc)})
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 3)


# ── Task 4: Session findings ingestion ───────────────────

@shared_task(
    name="pharma.rag.ingest_session_findings",
    queue="pharma.rag",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,
    reject_on_worker_lost=True,
)
def ingest_session_findings(
    self,
    session_id: str,
    drug_name: str,
    pillar: str,
    findings: dict[str, Any],
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Ingest completed session findings for few-shot RAG improvement.

    Called by the executor after a session completes with high confidence.
    These high-quality outputs become training examples for future queries
    on the same drug — reduces repeat API calls for popular drugs.

    Args:
        session_id: Completed session UUID.
        drug_name: Drug name analyzed.
        pillar: Pillar type string.
        findings: Agent findings dict.
        citations: Optional list of source citations.
    """
    from src.shared.rag.ingestion_pipeline import IngestionPipeline, from_session_findings

    start = time.perf_counter()
    try:
        doc = from_session_findings(session_id, drug_name, pillar, findings, citations)
        if not doc:
            return {"chunks_upserted": 0, "skipped": True}

        pipeline = IngestionPipeline()
        count = _run_async(pipeline.ingest_document(doc))
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        logger.info(
            "Session findings ingested for RAG",
            extra={"session_id": session_id, "drug_name": drug_name,
                   "pillar": pillar, "chunks": count, "latency_ms": elapsed_ms},
        )
        return {"chunks_upserted": count, "source_id": doc.source_id, "latency_ms": elapsed_ms}

    except Exception as exc:
        logger.error("Session findings ingest failed", extra={"error": str(exc), "session_id": session_id})
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 5)
