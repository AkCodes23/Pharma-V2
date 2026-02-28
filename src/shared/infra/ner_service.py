"""
Pharma Agentic AI — Azure AI Language NER Service.

Named Entity Recognition for pharmaceutical text using
Azure AI Language Text Analytics. Extracts Drug, Company,
Indication, Patent, and MechanismOfAction entities.

Architecture context:
  - Service: Shared infrastructure
  - Responsibility: NER extraction from unstructured text
  - Upstream: GraphClient.extract_and_store_entities(), RAG ingestion
  - Downstream: Azure AI Language endpoint
  - Failure: Falls back to regex heuristics on Azure failure
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from src.shared.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedEntity:
    """A named entity extracted from text."""
    text: str
    category: str  # Drug, Company, Indication, Patent, MechanismOfAction
    confidence: float
    offset: int = 0
    length: int = 0
    subcategory: str = ""


class NERService:
    """
    Named Entity Recognition service backed by Azure AI Language.

    Falls back to regex heuristics when Azure AI Language is
    unavailable or not configured.

    Usage:
        service = NERService()
        entities = await service.extract_entities(
            "Merck's Keytruda treats melanoma via PD-1 inhibition."
        )
    """

    def __init__(self) -> None:
        self._client = None
        self._initialized = False
        self._use_azure = False

    def _ensure_client(self) -> None:
        """Lazy-initialize the Azure AI Language client."""
        if self._initialized:
            return
        self._initialized = True

        settings = get_settings()
        if not hasattr(settings, "ai_language"):
            logger.info("AI Language config not found — using regex fallback")
            return

        ai_config = settings.ai_language
        if not ai_config.endpoint or not ai_config.api_key:
            logger.info("AI Language credentials missing — using regex fallback")
            return

        try:
            from azure.ai.textanalytics import TextAnalyticsClient
            from azure.core.credentials import AzureKeyCredential

            self._client = TextAnalyticsClient(
                endpoint=ai_config.endpoint,
                credential=AzureKeyCredential(ai_config.api_key),
            )
            self._use_azure = True
            logger.info("Azure AI Language NER service initialized")
        except Exception as e:
            logger.warning(
                "Azure AI Language init failed — using regex fallback",
                extra={"error": str(e)},
            )

    async def extract_entities(
        self,
        text: str,
        language: str = "en",
    ) -> list[ExtractedEntity]:
        """
        Extract pharmaceutical entities from text.

        Tries Azure AI Language first, falls back to regex heuristics.

        Args:
            text: Input text to analyze.
            language: Language code (default: "en").

        Returns:
            List of extracted entities with confidence scores.
        """
        if not text.strip():
            return []

        self._ensure_client()

        if self._use_azure and self._client is not None:
            try:
                return await self._azure_extract(text, language)
            except Exception as e:
                logger.warning(
                    "Azure NER failed — falling back to regex",
                    extra={"error": str(e), "text_len": len(text)},
                )

        return self._regex_extract(text)

    async def extract_entities_batch(
        self,
        texts: list[str],
        language: str = "en",
        batch_size: int = 10,
    ) -> list[list[ExtractedEntity]]:
        """
        Extract entities from multiple texts with batching.

        Azure AI Language supports up to 25 documents per batch.
        This method handles batching and concurrency limits.

        Args:
            texts: List of input texts.
            language: Language code.
            batch_size: Documents per batch (max 25 for Azure).

        Returns:
            List of entity lists, one per input text.
        """
        self._ensure_client()

        if self._use_azure and self._client is not None:
            try:
                return await self._azure_batch_extract(texts, language, batch_size)
            except Exception as e:
                logger.warning("Azure batch NER failed — regex fallback", extra={"error": str(e)})

        return [self._regex_extract(t) for t in texts]

    async def _azure_extract(
        self,
        text: str,
        language: str,
    ) -> list[ExtractedEntity]:
        """Extract entities using Azure AI Language Text Analytics."""
        import asyncio

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._client.recognize_entities(  # type: ignore[union-attr]
                documents=[{"id": "1", "text": text, "language": language}],
            ),
        )

        entities: list[ExtractedEntity] = []
        for doc in result:
            if doc.is_error:
                logger.warning("Azure NER doc error", extra={"error": doc.error.message})
                continue
            for entity in doc.entities:
                # Map Azure categories to our pharma entity types
                pharma_category = _map_azure_category(entity.category, entity.subcategory or "")
                if pharma_category:
                    entities.append(ExtractedEntity(
                        text=entity.text,
                        category=pharma_category,
                        confidence=entity.confidence_score,
                        offset=entity.offset,
                        length=entity.length,
                        subcategory=entity.subcategory or "",
                    ))

        return entities

    async def _azure_batch_extract(
        self,
        texts: list[str],
        language: str,
        batch_size: int,
    ) -> list[list[ExtractedEntity]]:
        """Extract entities from a batch of documents."""
        import asyncio

        all_results: list[list[ExtractedEntity]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            documents = [
                {"id": str(j), "text": t, "language": language}
                for j, t in enumerate(batch)
            ]

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda docs=documents: self._client.recognize_entities(documents=docs),  # type: ignore[union-attr]
            )

            for doc in result:
                if doc.is_error:
                    all_results.append([])
                    continue
                doc_entities = []
                for entity in doc.entities:
                    pharma_category = _map_azure_category(entity.category, entity.subcategory or "")
                    if pharma_category:
                        doc_entities.append(ExtractedEntity(
                            text=entity.text,
                            category=pharma_category,
                            confidence=entity.confidence_score,
                            offset=entity.offset,
                            length=entity.length,
                            subcategory=entity.subcategory or "",
                        ))
                all_results.append(doc_entities)

        return all_results

    def _regex_extract(self, text: str) -> list[ExtractedEntity]:
        """
        Fallback NER using regex heuristics.

        Matches known pharmaceutical patterns:
          - Drug names: Capitalized words with common pharma suffixes
          - Companies: "Inc.", "Ltd.", "Pharma", etc.
          - Indications: Known disease patterns
          - Patents: US/EP/IN patent number patterns
        """
        entities: list[ExtractedEntity] = []

        # Drug names — common pharma suffixes
        drug_patterns = [
            r"\b([A-Z][a-z]+(?:mab|nib|lib|zumab|tinib|ciclib|lutamide|rafenib|parin|vastatin|olol|pril|sartan))\b",
            r"\b((?:Pembro|Nivo|Atezo|Durva|Avelu|Ipili|Trast|Beva|Ritu|Adali)(?:lizumab|zumab|mumab|ximab))\b",
        ]
        for pattern in drug_patterns:
            for match in re.finditer(pattern, text):
                entities.append(ExtractedEntity(
                    text=match.group(1),
                    category="Drug",
                    confidence=0.7,
                    offset=match.start(),
                    length=len(match.group(1)),
                ))

        # Company names
        company_pattern = r"\b([A-Z][A-Za-z&\s]+(?:Inc\.|Ltd\.|Corp\.|Pharma|Therapeutics|Biosciences|Biotech))\b"
        for match in re.finditer(company_pattern, text):
            entities.append(ExtractedEntity(
                text=match.group(1).strip(),
                category="Company",
                confidence=0.6,
                offset=match.start(),
                length=len(match.group(1)),
            ))

        # Patent numbers
        patent_pattern = r"\b((?:US|EP|WO|IN|JP)\s*\d{5,}(?:\s*[AB]\d?)?)\b"
        for match in re.finditer(patent_pattern, text):
            entities.append(ExtractedEntity(
                text=match.group(1),
                category="Patent",
                confidence=0.9,
                offset=match.start(),
                length=len(match.group(1)),
            ))

        # Deduplicate by text + category
        seen: set[tuple[str, str]] = set()
        unique: list[ExtractedEntity] = []
        for e in entities:
            key = (e.text.lower(), e.category)
            if key not in seen:
                seen.add(key)
                unique.append(e)

        return unique


def _map_azure_category(category: str, subcategory: str) -> str | None:
    """Map Azure AI Language entity categories to pharma domain categories."""
    mapping: dict[str, str] = {
        "Product": "Drug",
        "Organization": "Company",
        "Event": "Indication",
        "Skill": "MechanismOfAction",
    }

    # Healthcare-specific mapping
    healthcare_mapping: dict[str, str] = {
        "MedicationName": "Drug",
        "Diagnosis": "Indication",
        "MedicalCondition": "Indication",
        "BodyStructure": "Indication",
        "TreatmentName": "MechanismOfAction",
    }

    # Try healthcare mapping first (more specific)
    if subcategory in healthcare_mapping:
        return healthcare_mapping[subcategory]

    return mapping.get(category)


# Module-level singleton
_ner_service: NERService | None = None


def get_ner_service() -> NERService:
    """Return shared NERService singleton."""
    global _ner_service
    if _ner_service is None:
        _ner_service = NERService()
    return _ner_service
