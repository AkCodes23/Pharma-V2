"""
Unit tests for the RAG pipeline components.

Tests: chunker, ingestion pipeline document builders,
embedding service caching, and RAG retriever filtering logic.

Does NOT call Azure AI Search or Azure OpenAI — all external
services are mocked so tests run offline.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Chunker tests ─────────────────────────────────────────

class TestChunker:
    """Tests for the recursive character splitter."""

    def test_short_text_returns_single_chunk(self):
        from src.shared.rag.chunker import chunk_text
        result = chunk_text("Short text.", chunk_size=512)
        assert result == ["Short text."]

    def test_empty_text_returns_empty_list(self):
        from src.shared.rag.chunker import chunk_text
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_long_text_produces_multiple_chunks(self):
        from src.shared.rag.chunker import chunk_text
        # 600 words should exceed 512-token chunk
        long_text = "The drug Semaglutide demonstrated efficacy. " * 100
        chunks = chunk_text(long_text, chunk_size=50, chunk_overlap=5)
        assert len(chunks) > 1

    def test_chunks_respect_size_limit(self):
        from src.shared.rag.chunker import chunk_text, _CHARS_PER_TOKEN
        long_text = "Semaglutide clinical trial. " * 200
        chunk_size = 50
        chunks = chunk_text(long_text, chunk_size=chunk_size)
        max_chars = chunk_size * _CHARS_PER_TOKEN * 1.2  # 20% tolerance
        for chunk in chunks:
            assert len(chunk) <= max_chars, f"Chunk too long: {len(chunk)} chars"

    def test_chunk_document_preserves_metadata(self):
        from src.shared.rag.chunker import chunk_document, Document
        doc = Document(
            content="FDA approved Semaglutide in 2021 for obesity treatment. " * 30,
            source_id="fda-nda-nda213051",
            pillar="LEGAL",
            drug_name="semaglutide",
            session_id="session-001",
        )
        chunks = chunk_document(doc, chunk_size=50, chunk_overlap=5)
        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.source_id == "fda-nda-nda213051"
            assert chunk.pillar == "LEGAL"
            assert chunk.drug_name == "semaglutide"
            assert chunk.session_id == "session-001"
            assert 0 <= chunk.chunk_index < chunk.total_chunks

    def test_chunk_indices_are_sequential(self):
        from src.shared.rag.chunker import chunk_document, Document
        doc = Document(content="A B C D E F G. " * 100, source_id="test", pillar="LEGAL")
        chunks = chunk_document(doc, chunk_size=30, chunk_overlap=3)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))
        assert all(c.total_chunks == len(chunks) for c in chunks)

    def test_empty_document_returns_empty_list(self):
        from src.shared.rag.chunker import chunk_document, Document
        doc = Document(content="", source_id="empty", pillar="LEGAL")
        assert chunk_document(doc) == []

    def test_estimate_chunk_count_positive(self):
        from src.shared.rag.chunker import estimate_chunk_count
        count = estimate_chunk_count("word " * 1000, chunk_size=100, chunk_overlap=10)
        assert count > 0


# ── Ingestion pipeline document builders ─────────────────

class TestDocumentBuilders:
    """Tests for source-type-specific Document factory functions."""

    def test_from_fda_response_valid(self):
        from src.shared.rag.ingestion_pipeline import from_fda_response
        fda_data = {
            "sponsor_name": "Novo Nordisk",
            "application_number": "NDA213051",
            "openfda": {
                "brand_name": ["Ozempic"],
                "generic_name": ["semaglutide"],
            },
            "products": [{"route": "SUBCUTANEOUS", "dosage_form": "INJECTION",
                          "marketing_status": "Prescription"}],
            "submissions": [{"submission_type": "ORIG", "action_date": "2021-06-04",
                             "submission_status": "AP"}],
        }
        doc = from_fda_response(fda_data, "semaglutide", "session-001")
        assert doc is not None
        assert doc.pillar == "LEGAL"
        assert doc.drug_name == "semaglutide"
        assert "Novo Nordisk" in doc.content
        assert "NDA213051" in doc.content
        assert doc.source_id  # non-empty

    def test_from_fda_response_empty_returns_none(self):
        from src.shared.rag.ingestion_pipeline import from_fda_response
        doc = from_fda_response({}, "semaglutide")
        assert doc is None

    def test_from_clinical_trial_valid(self):
        from src.shared.rag.ingestion_pipeline import from_clinical_trial
        trial = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT04788433", "briefTitle": "SURMOUNT-1"},
                "statusModule": {"overallStatus": "COMPLETED"},
                "designModule": {"phases": ["Phase 3"], "enrollmentInfo": {"count": 2539}},
                "conditionsModule": {"conditions": ["Obesity"]},
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Eli Lilly"}},
                "descriptionModule": {"briefSummary": "Phase 3 trial of tirzepatide."},
                "eligibilityModule": {"eligibilityCriteria": "BMI >= 30"},
                "outcomesModule": {"primaryOutcomes": [{"measure": "Weight loss at 72 weeks"}]},
            }
        }
        doc = from_clinical_trial(trial, "tirzepatide")
        assert doc is not None
        assert doc.pillar == "CLINICAL"
        assert "NCT04788433" in doc.content
        assert "SURMOUNT-1" in doc.content

    def test_from_clinical_trial_no_nct_returns_none(self):
        from src.shared.rag.ingestion_pipeline import from_clinical_trial
        doc = from_clinical_trial({}, "drug")
        assert doc is None

    def test_from_news_article_valid(self):
        from src.shared.rag.ingestion_pipeline import from_news_article
        article = {
            "url": "https://example.com/news/semaglutide",
            "title": "Semaglutide shows 20% weight loss in trial",
            "content": "A " * 60 + "long article about semaglutide.",
            "score": 0.95,
        }
        doc = from_news_article(article, "semaglutide")
        assert doc is not None
        assert doc.pillar == "NEWS"
        assert "semaglutide" in doc.content.lower()

    def test_from_news_article_too_short_returns_none(self):
        from src.shared.rag.ingestion_pipeline import from_news_article
        # Content < 100 chars should be skipped
        doc = from_news_article({"content": "Short.", "url": "http://x.com"}, "drug")
        assert doc is None

    def test_from_session_findings_valid(self):
        from src.shared.rag.ingestion_pipeline import from_session_findings
        findings = {"approval_status": "Approved", "competitor_count": 3, "confidence": 0.9}
        doc = from_session_findings("sess-001", "semaglutide", "COMMERCIAL", findings)
        assert doc is not None
        assert doc.pillar == "COMMERCIAL"
        assert doc.session_id == "sess-001"
        assert "approval_status" in doc.content

    def test_source_id_is_stable(self):
        """Same inputs → same source_id (idempotency)."""
        from src.shared.rag.ingestion_pipeline import from_fda_response
        fda_data = {
            "sponsor_name": "Test", "application_number": "NDA999",
            "openfda": {"brand_name": ["TestDrug"], "generic_name": ["testdrug"]},
            "products": [], "submissions": [],
        }
        doc1 = from_fda_response(fda_data, "testdrug")
        doc2 = from_fda_response(fda_data, "testdrug")
        assert doc1.source_id == doc2.source_id


# ── Embedding service tests ───────────────────────────────

class TestEmbeddingService:
    """Tests for embedding caching and batch logic."""

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_api_call(self):
        from src.shared.infra.embedding_service import EmbeddingService
        svc = EmbeddingService()
        fake_vector = [0.1] * 1536
        svc._store_cache("test text", fake_vector)

        with patch.object(svc, "_call_api", new_callable=AsyncMock) as mock_api:
            result = await svc.embed("test text")
            mock_api.assert_not_called()
            assert result == fake_vector
            assert svc._cache_hits == 1

    @pytest.mark.asyncio
    async def test_empty_text_returns_zero_vector(self):
        from src.shared.infra.embedding_service import EmbeddingService, EMBEDDING_DIMENSIONS
        svc = EmbeddingService()
        result = await svc.embed("")
        assert result == [0.0] * EMBEDDING_DIMENSIONS

    @pytest.mark.asyncio
    async def test_embed_batch_empty_list(self):
        from src.shared.infra.embedding_service import EmbeddingService
        svc = EmbeddingService()
        result = await svc.embed_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_batch_partial_cache(self):
        from src.shared.infra.embedding_service import EmbeddingService
        svc = EmbeddingService()
        cached_vector = [0.5] * 1536
        svc._store_cache("cached text", cached_vector)

        uncached_vector = [0.9] * 1536
        with patch.object(svc, "_call_api", new_callable=AsyncMock,
                          return_value=[uncached_vector]) as mock_api:
            results = await svc.embed_batch(["cached text", "new text"])
            assert results[0] == cached_vector
            assert results[1] == uncached_vector
            mock_api.assert_called_once_with(["new text"])

    def test_stats_initial_zero(self):
        from src.shared.infra.embedding_service import EmbeddingService
        svc = EmbeddingService()
        stats = svc.get_stats()
        assert stats["total_requests"] == 0
        assert stats["cache_size"] == 0


# ── RAG retriever score filtering tests ──────────────────

class TestRagRetrieverFiltering:
    """Tests for score-based result filtering without Azure calls."""

    def test_filter_drops_low_reranker_score(self):
        from src.shared.rag.rag_retriever import _filter_and_rank, SEMANTIC_SCORE_THRESHOLD
        raw = [
            {"content": "high", "score": 0.9, "reranker_score": 3.5,
             "source_id": "s1", "pillar": "LEGAL", "drug_name": "drug",
             "chunk_index": 0, "extra_metadata": ""},
            {"content": "low", "score": 0.5, "reranker_score": 1.0,
             "source_id": "s2", "pillar": "LEGAL", "drug_name": "drug",
             "chunk_index": 0, "extra_metadata": ""},
        ]
        chunks = _filter_and_rank(raw, min_score=None)
        assert len(chunks) == 1
        assert chunks[0].content == "high"

    def test_filter_sorts_by_reranker_desc(self):
        from src.shared.rag.rag_retriever import _filter_and_rank
        raw = [
            {"content": "medium", "score": 0.7, "reranker_score": 2.5,
             "source_id": "s1", "pillar": "LEGAL", "drug_name": "drug",
             "chunk_index": 0, "extra_metadata": ""},
            {"content": "best", "score": 0.6, "reranker_score": 3.9,
             "source_id": "s2", "pillar": "LEGAL", "drug_name": "drug",
             "chunk_index": 0, "extra_metadata": ""},
        ]
        chunks = _filter_and_rank(raw, min_score=2.0)
        assert chunks[0].content == "best"
        assert chunks[1].content == "medium"

    def test_empty_context_is_empty(self):
        from src.shared.rag.rag_retriever import _empty_context
        ctx = _empty_context(["LEGAL"])
        assert ctx.is_empty
        assert ctx.formatted_context == ""
        assert ctx.total_retrieved == 0

    def test_build_context_formats_correctly(self):
        from src.shared.rag.rag_retriever import _build_context, RagChunk
        chunks = [
            RagChunk(content="FDA approved Ozempic.", source_id="nda-213051",
                     pillar="LEGAL", drug_name="semaglutide", score=0.9,
                     reranker_score=3.5),
        ]
        ctx = _build_context(chunks, pillars=["LEGAL"])
        assert not ctx.is_empty
        assert "=== Retrieved Knowledge ===" in ctx.formatted_context
        assert "FDA approved Ozempic." in ctx.formatted_context
        assert "nda-213051" in ctx.formatted_context
        assert len(ctx.citations) == 1
        assert ctx.citations[0]["source_id"] == "nda-213051"
