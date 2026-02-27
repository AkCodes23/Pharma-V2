"""
Pharma Agentic AI — Celery Tasks: RAG Indexing.

Background tasks for document ingestion, chunking, embedding,
and vector store indexing.

Architecture context:
  - Queue: pharma.rag
  - Responsibility: Document ingestion pipeline
  - Upstream: API upload endpoint, Celery Beat (re-indexing schedule)
  - Downstream: Vector Store (ChromaDB local / Azure AI Search prod)
"""

from __future__ import annotations

import logging

from src.shared.infra.celery_app import app

logger = logging.getLogger(__name__)


@app.task(
    name="src.shared.tasks.rag_task.ingest_document",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    queue="pharma.rag",
)
def ingest_document(self, document_id: str, file_path: str, doc_type: str) -> dict:
    """
    Ingest a document into the RAG pipeline.

    Pipeline:
      1. Extract text (PDF/CSV/HTML)
      2. Chunk with overlap (512 tokens, 50 overlap)
      3. Generate embeddings via Azure OpenAI
      4. Store in vector index

    Args:
        document_id: UUID of the document record.
        file_path: Path to the file (local or blob URL).
        doc_type: File type (pdf, csv, html).

    Returns:
        Dict with chunk_count and status.
    """
    try:
        from src.agents.retrievers.knowledge.rag_engine import RAGEngine

        engine = RAGEngine()
        result = engine.ingest(
            document_id=document_id,
            file_path=file_path,
            doc_type=doc_type,
        )

        logger.info(
            "Document ingested via Celery",
            extra={
                "document_id": document_id,
                "chunk_count": result.get("chunk_count", 0),
            },
        )
        return result

    except Exception as exc:
        logger.exception("Document ingestion failed", extra={"document_id": document_id})
        raise self.retry(exc=exc)


@app.task(
    name="src.shared.tasks.rag_task.reindex_documents",
    queue="pharma.rag",
)
def reindex_documents() -> dict:
    """
    Re-index all documents in the RAG pipeline.

    Scheduled by Celery Beat at 2 AM UTC daily.
    Rebuilds the vector index from scratch.
    """
    try:
        from src.agents.retrievers.knowledge.rag_engine import RAGEngine

        engine = RAGEngine()
        result = engine.reindex_all()

        logger.info("RAG re-indexing completed", extra={"result": result})
        return result

    except Exception:
        logger.exception("RAG re-indexing failed")
        return {"status": "failed"}
