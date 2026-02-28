"""
Unit tests for NER Service.

Tests Azure AI Language integration (mocked) and regex fallback
for pharmaceutical entity extraction.
"""

from __future__ import annotations

import pytest

from src.shared.infra.ner_service import (
    NERService,
    ExtractedEntity,
    _map_azure_category,
)


class TestNERServiceRegexFallback:
    """Tests for regex-based entity extraction (fallback)."""

    def setup_method(self) -> None:
        self.service = NERService()
        # Force regex mode
        self.service._initialized = True
        self.service._use_azure = False

    def test_extracts_drug_names(self) -> None:
        text = "Pembrolizumab is a monoclonal antibody targeting PD-1."
        entities = self.service._regex_extract(text)
        drug_entities = [e for e in entities if e.category == "Drug"]
        assert len(drug_entities) >= 1
        assert any("Pembrolizumab" in e.text for e in drug_entities)

    def test_extracts_company_names(self) -> None:
        text = "Merck Pharma is developing a new immunotherapy."
        entities = self.service._regex_extract(text)
        company_entities = [e for e in entities if e.category == "Company"]
        assert len(company_entities) >= 1

    def test_extracts_patent_numbers(self) -> None:
        text = "The compound is protected under US 10123456 and EP 3456789."
        entities = self.service._regex_extract(text)
        patent_entities = [e for e in entities if e.category == "Patent"]
        assert len(patent_entities) >= 1

    def test_empty_text_returns_empty(self) -> None:
        entities = self.service._regex_extract("")
        assert entities == []

    def test_deduplication(self) -> None:
        text = "Pembrolizumab was compared to Pembrolizumab in a cross-over study."
        entities = self.service._regex_extract(text)
        drug_names = [e.text for e in entities if e.category == "Drug"]
        # Should deduplicate
        assert len(set(drug_names)) == len(drug_names)

    def test_drug_suffix_patterns(self) -> None:
        """Test that common pharmaceutical suffixes are recognized."""
        suffixes_text = "Trastuzumab, Imatinib, and Atorvastatin are well-known drugs."
        entities = self.service._regex_extract(suffixes_text)
        drug_entities = [e for e in entities if e.category == "Drug"]
        assert len(drug_entities) >= 1


class TestNERServiceAsync:
    """Tests for async extract_entities method."""

    @pytest.mark.asyncio
    async def test_extract_entities_regex_fallback(self) -> None:
        service = NERService()
        service._initialized = True
        service._use_azure = False

        entities = await service.extract_entities("Pembrolizumab treats melanoma.")
        assert isinstance(entities, list)

    @pytest.mark.asyncio
    async def test_empty_text(self) -> None:
        service = NERService()
        entities = await service.extract_entities("")
        assert entities == []

    @pytest.mark.asyncio
    async def test_whitespace_only(self) -> None:
        service = NERService()
        entities = await service.extract_entities("   ")
        assert entities == []


class TestMapAzureCategory:
    """Tests for Azure entity category mapping."""

    def test_product_maps_to_drug(self) -> None:
        assert _map_azure_category("Product", "") == "Drug"

    def test_organization_maps_to_company(self) -> None:
        assert _map_azure_category("Organization", "") == "Company"

    def test_medication_subcategory(self) -> None:
        assert _map_azure_category("", "MedicationName") == "Drug"

    def test_diagnosis_subcategory(self) -> None:
        assert _map_azure_category("", "Diagnosis") == "Indication"

    def test_unknown_category_returns_none(self) -> None:
        assert _map_azure_category("Location", "") is None

    def test_subcategory_takes_priority(self) -> None:
        # Subcategory "MedicationName" should win over category
        result = _map_azure_category("Organization", "MedicationName")
        assert result == "Drug"
