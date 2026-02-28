"""
Pharma Agentic AI — RAG Ingestion Pipeline.

Orchestrates the full document ingestion path:
  Document → chunks → embeddings → Azure AI Search upsert

Architecture context:
  - Service: Shared RAG infrastructure
  - Responsibility: Batch and single-document ingestion
  - Upstream: Celery ingestion tasks, manual admin ingestion
  - Downstream: EmbeddingService → AISearchRAGClient
  - Failure: Chunk-level errors logged, pipeline continues
  - Idempotency: Same source_id+chunk_index → upsert (no duplicates)

Performance:
  - embed_batch() runs all chunks through Azure OpenAI concurrently
  - Upsert batched at 1000 docs per API call (AI Search limit)
  - Progress reported via structured logs (pick up by OpenTelemetry)

Document build helpers:
  - from_fda_response()      — FDA OpenFDA API JSON → Document
  - from_clinical_trial()    — ClinicalTrials.gov study JSON → Document
  - from_news_article()      — Tavily result dict → Document
  - from_session_findings()  — Completed session result → Document
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from src.shared.infra.ai_search_client import (
    AISearchRAGClient,
    _build_search_document,
    get_ai_search_client,
)
from src.shared.infra.embedding_service import EmbeddingService, get_embedding_service
from src.shared.rag.chunker import Chunk, Document, chunk_document

logger = logging.getLogger(__name__)


# ── Ingestion Pipeline ────────────────────────────────────

class IngestionPipeline:
    """
    End-to-end RAG ingestion pipeline.

    Usage:
        pipeline = IngestionPipeline()
        await pipeline.initialize()

        doc = Document(content="...", source_id="nda-123456",
                       pillar="LEGAL", drug_name="semaglutide")
        count = await pipeline.ingest_document(doc)
        print(f"Ingested {count} chunks")
    """

    def __init__(
        self,
        search_client: AISearchRAGClient | None = None,
        embedding_service: EmbeddingService | None = None,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ) -> None:
        self._search = search_client or get_ai_search_client()
        self._embedder = embedding_service or get_embedding_service()
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def initialize(self) -> None:
        """Ensure all Azure AI Search indexes exist."""
        await self._search.initialize()

    async def ingest_document(self, doc: Document) -> int:
        """
        Ingest a single document: chunk → embed → upsert.

        Args:
            doc: Source document to ingest.

        Returns:
            Number of chunks successfully upserted.
        """
        start = time.perf_counter()

        chunks = chunk_document(doc, self._chunk_size, self._chunk_overlap)
        if not chunks:
            logger.warning(
                "Document produced no chunks — skipping",
                extra={"source_id": doc.source_id, "pillar": doc.pillar},
            )
            return 0

        # Embed all chunk texts concurrently
        texts = [c.text for c in chunks]
        try:
            vectors = await self._embedder.embed_batch(texts)
        except Exception as e:
            logger.error(
                "Embedding failed for document",
                extra={"source_id": doc.source_id, "error": str(e)},
            )
            return 0

        # Build search documents
        search_docs = [
            _build_search_document(
                source_id=chunk.source_id,
                chunk_index=chunk.chunk_index,
                total_chunks=chunk.total_chunks,
                content=chunk.text,
                vector=vectors[i],
                pillar=chunk.pillar,
                drug_name=chunk.drug_name,
                session_id=chunk.session_id,
                extra_metadata=chunk.metadata,
            )
            for i, chunk in enumerate(chunks)
        ]

        upserted = await self._search.upsert_chunks(search_docs, pillar=doc.pillar)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        logger.info(
            "Document ingested",
            extra={
                "source_id": doc.source_id,
                "pillar": doc.pillar,
                "drug_name": doc.drug_name,
                "chunks": len(chunks),
                "upserted": upserted,
                "latency_ms": elapsed_ms,
            },
        )
        return upserted

    async def ingest_batch(self, docs: list[Document]) -> dict[str, int]:
        """
        Ingest multiple documents.

        Runs sequentially to avoid overwhelming Azure OpenAI rate limits.
        For true parallel ingestion, use Celery tasks instead.

        Returns:
            Dict mapping source_id → chunks upserted.
        """
        results: dict[str, int] = {}
        for doc in docs:
            try:
                count = await self.ingest_document(doc)
                results[doc.source_id] = count
            except Exception as e:
                logger.error(
                    "Batch ingestion error — skipping document",
                    extra={"source_id": doc.source_id, "error": str(e)},
                )
                results[doc.source_id] = 0
        return results

    async def re_ingest(self, doc: Document) -> int:
        """
        Delete existing chunks for a source, then re-ingest.
        Use when a document has been updated.
        """
        deleted = await self._search.delete_by_source(doc.source_id, doc.pillar)
        logger.info("Re-ingesting document", extra={"source_id": doc.source_id, "deleted": deleted})
        return await self.ingest_document(doc)


# ── Document builders for each source type ────────────────

def _stable_source_id(*parts: str) -> str:
    """Build a stable SHA-256 source ID from parts."""
    raw = "::".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def from_fda_response(
    fda_data: dict[str, Any],
    drug_name: str,
    session_id: str = "",
) -> Document | None:
    """
    Build a Document from an FDA OpenFDA API response dict.

    Extracts: brand name, generic name, applicant, approval dates,
    labeling text, warnings, indications sections.

    Returns None if no meaningful content found.
    """
    content_parts: list[str] = []

    # Top-level metadata
    sponsor = fda_data.get("sponsor_name", "")
    app_num = fda_data.get("application_number", "")
    if sponsor:
        content_parts.append(f"Sponsor: {sponsor}")
    if app_num:
        content_parts.append(f"Application Number: {app_num}")

    openfda = fda_data.get("openfda", {})
    brand_names = openfda.get("brand_name", [])
    generic_names = openfda.get("generic_name", [])
    if brand_names:
        content_parts.append(f"Brand Name: {', '.join(brand_names)}")
    if generic_names:
        content_parts.append(f"Generic Name: {', '.join(generic_names)}")

    # Product information
    for product in fda_data.get("products", [])[:5]:
        route = product.get("route", "")
        dosage = product.get("dosage_form", "")
        status = product.get("marketing_status", "")
        if route or dosage:
            content_parts.append(f"Form/Route: {dosage} / {route} | Status: {status}")

    # Submission history
    for sub in fda_data.get("submissions", [])[:3]:
        sub_type = sub.get("submission_type", "")
        action_date = sub.get("action_date", "")
        action = sub.get("submission_status", "")
        if sub_type and action_date:
            content_parts.append(f"Submission: {sub_type} on {action_date} — {action}")

    content = "\n".join(content_parts)
    if not content.strip():
        return None

    source_id = _stable_source_id("fda", app_num or drug_name)
    return Document(
        content=content,
        source_id=source_id,
        pillar="LEGAL",
        drug_name=drug_name,
        session_id=session_id,
        title=f"FDA Record: {', '.join(brand_names) or drug_name}",
        metadata={"application_number": app_num, "sponsor": sponsor, "source": "fda_openfda"},
    )


def from_clinical_trial(
    trial_data: dict[str, Any],
    drug_name: str,
    session_id: str = "",
) -> Document | None:
    """
    Build a Document from a ClinicalTrials.gov study object (API v2 format).

    Extracts: title, status, phase, enrollment, eligibility, outcomes,
    conditions, sponsor, start/end dates.
    """
    proto = trial_data.get("protocolSection", {})
    id_mod = proto.get("identificationModule", {})
    status_mod = proto.get("statusModule", {})
    design_mod = proto.get("designModule", {})
    cond_mod = proto.get("conditionsModule", {})
    eligibility_mod = proto.get("eligibilityModule", {})
    outcomes_mod = proto.get("outcomesModule", {})
    sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
    desc_mod = proto.get("descriptionModule", {})

    nct_id = id_mod.get("nctId", "")
    title = id_mod.get("briefTitle", "")
    status = status_mod.get("overallStatus", "")
    phases = design_mod.get("phases", [])
    enrollment = design_mod.get("enrollmentInfo", {}).get("count", 0)
    conditions = cond_mod.get("conditions", [])
    sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "")
    brief_summary = desc_mod.get("briefSummary", "")
    criteria = eligibility_mod.get("eligibilityCriteria", "")

    content_parts: list[str] = [f"Trial: {title}", f"NCT ID: {nct_id}",
                                  f"Status: {status}", f"Phase: {', '.join(phases)}",
                                  f"Enrollment: {enrollment}", f"Sponsor: {sponsor}"]
    if conditions:
        content_parts.append(f"Conditions: {', '.join(conditions[:5])}")
    if brief_summary:
        content_parts.append(f"Summary: {brief_summary[:1000]}")
    if criteria:
        content_parts.append(f"Eligibility: {criteria[:1000]}")

    # Primary outcomes
    for outcome in outcomes_mod.get("primaryOutcomes", [])[:3]:
        measure = outcome.get("measure", "")
        if measure:
            content_parts.append(f"Primary Outcome: {measure}")

    content = "\n".join(content_parts)
    if not content.strip() or not nct_id:
        return None

    return Document(
        content=content,
        source_id=_stable_source_id("ct", nct_id),
        pillar="CLINICAL",
        drug_name=drug_name,
        session_id=session_id,
        title=f"Trial: {title[:80]}",
        metadata={"nct_id": nct_id, "status": status, "phases": phases,
                  "sponsor": sponsor, "source": "clinicaltrials_gov"},
    )


def from_news_article(
    article: dict[str, Any],
    drug_name: str,
    session_id: str = "",
) -> Document | None:
    """
    Build a Document from a Tavily search result dict.

    Expected keys: url, title, content, score, published_date.
    """
    content = article.get("content", "").strip()
    url = article.get("url", "")
    title = article.get("title", "")
    published = article.get("published_date", "")

    if not content or len(content) < 100:
        return None

    full_content = f"Title: {title}\nPublished: {published}\nSource: {url}\n\n{content}"

    return Document(
        content=full_content,
        source_id=_stable_source_id("news", url or title),
        pillar="NEWS",
        drug_name=drug_name,
        session_id=session_id,
        title=title[:120],
        metadata={"url": url, "published_date": published,
                  "relevance_score": article.get("score", 0.0), "source": "tavily"},
    )


def from_session_findings(
    session_id: str,
    drug_name: str,
    pillar: str,
    findings: dict[str, Any],
    citations: list[dict[str, Any]] | None = None,
) -> Document | None:
    """
    Build a Document from completed session agent findings.

    These are high-quality, already-evaluated outputs that can
    be used as few-shot examples for future similar drug queries.
    """
    if not findings:
        return None

    content_parts = [f"Drug: {drug_name}", f"Pillar: {pillar}",
                     f"Session: {session_id}", ""]

    # Flatten findings dict into readable text
    for key, value in findings.items():
        if isinstance(value, (str, int, float)):
            content_parts.append(f"{key}: {value}")
        elif isinstance(value, list):
            content_parts.append(f"{key}: {', '.join(str(v) for v in value[:10])}")
        elif isinstance(value, dict):
            content_parts.append(f"{key}: {json.dumps(value, default=str)[:500]}")

    if citations:
        content_parts.append("\nCitations:")
        for c in citations[:5]:
            content_parts.append(f"  - {c.get('title', '')} ({c.get('url', '')})")

    content = "\n".join(content_parts)

    return Document(
        content=content,
        source_id=_stable_source_id("session", session_id, pillar),
        pillar=pillar,
        drug_name=drug_name,
        session_id=session_id,
        title=f"Session Findings: {drug_name} / {pillar}",
        metadata={"source": "session_output", "confidence": findings.get("confidence", 0)},
    )
