"""
Pharma Agentic AI — Document Chunker.

Splits long documents into overlapping text chunks suitable
for embedding and vector search. Designed for pharma-specific
content: FDA submissions, clinical trial protocols, patents,
market reports.

Architecture context:
  - Service: Shared RAG infrastructure
  - Responsibility: Document → Chunk[] conversion
  - Upstream: IngestionPipeline
  - Downstream: EmbeddingService
  - No I/O: pure Python, deterministic, testable

Chunking strategy:
  Recursive character splitting with configurable chunk_size and overlap.
  Priority separator order: paragraph → sentence → word → character.
  This preserves natural language boundaries for better embedding quality.

  chunk_size=512 tokens ≈ 2048 characters (4 chars/token average)
  chunk_overlap=50 tokens ≈ 200 characters (context continuity)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── Data models ───────────────────────────────────────────

@dataclass
class Document:
    """
    A source document to be chunked and ingested into the RAG pipeline.

    source_id must be globally unique and stable — it becomes the
    de-duplication key. Good values: URL, NDA number, session_id+pillar.
    """
    content: str                           # Full document text
    source_id: str                         # Unique stable identifier
    pillar: str                            # PillarType string e.g. "LEGAL"
    drug_name: str = ""                    # Normalized drug name
    session_id: str = ""                   # Source session (optional)
    title: str = ""                        # Human-readable title
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """
    A single text chunk ready for embedding and vector upsert.

    Preserves all parent document metadata so search results
    can trace back to the original source.
    """
    text: str                              # Chunk text (stripped)
    source_id: str                         # Parent document source_id
    chunk_index: int                       # Position in document (0-based)
    total_chunks: int                      # Total chunks in document
    pillar: str                            # Inherited from Document
    drug_name: str = ""                    # Inherited from Document
    session_id: str = ""                   # Inherited from Document
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Recursive character splitter ──────────────────────────

# Separator priority: paragraph → sentence boundary → clause → word → char
_SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""]

# Approximate chars per token for pharma text (conservative estimate)
_CHARS_PER_TOKEN = 4


def _approx_tokens(text: str) -> int:
    """Approximate token count from character count."""
    return len(text) // _CHARS_PER_TOKEN


def _split_recursive(
    text: str,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    separators: list[str],
) -> list[str]:
    """
    Recursively split text trying each separator in priority order.

    If the text fits within chunk_size_chars, returns it as-is.
    Otherwise tries each separator to find natural boundaries.
    Falls back to hard character splits if no separator works.
    """
    if len(text) <= chunk_size_chars:
        stripped = text.strip()
        return [stripped] if stripped else []

    # Try each separator in priority order
    for sep in separators:
        if sep == "":
            # Hard split — last resort
            chunks = []
            for i in range(0, len(text), chunk_size_chars - chunk_overlap_chars):
                chunk = text[i : i + chunk_size_chars].strip()
                if chunk:
                    chunks.append(chunk)
            return chunks

        if sep not in text:
            continue

        # Split on this separator, then recursively process large pieces
        parts = text.split(sep)
        chunks: list[str] = []
        current = ""

        for part in parts:
            candidate = current + sep + part if current else part
            if len(candidate) <= chunk_size_chars:
                current = candidate
            else:
                # current chunk is ready — flush it
                if current.strip():
                    if len(current) > chunk_size_chars:
                        # Recurse with next separator
                        chunks.extend(_split_recursive(
                            current, chunk_size_chars, chunk_overlap_chars,
                            separators[separators.index(sep) + 1:]
                        ))
                    else:
                        chunks.append(current.strip())
                # Start new chunk with overlap from end of current
                if current and chunk_overlap_chars > 0:
                    overlap_text = current[-chunk_overlap_chars:]
                    current = overlap_text + sep + part
                else:
                    current = part

        if current.strip():
            chunks.append(current.strip())

        if chunks:
            return chunks

    return [text.strip()] if text.strip() else []


# ── Public API ────────────────────────────────────────────

def chunk_text(
    text: str,
    chunk_size: int = 512,      # tokens
    chunk_overlap: int = 50,    # tokens
) -> list[str]:
    """
    Split text into overlapping chunks of approximately `chunk_size` tokens.

    Args:
        text: Input text (any length).
        chunk_size: Target chunk size in tokens (default 512 ≈ 2048 chars).
        chunk_overlap: Overlap between consecutive chunks in tokens (default 50).

    Returns:
        List of chunk strings. Empty strings are excluded.

    Example:
        >>> chunks = chunk_text("Long pharma document...", chunk_size=512)
        >>> len(chunks[0]) <= 2048  # char limit
        True
    """
    if not text or not text.strip():
        return []

    # Normalize whitespace: collapse multiple blank lines to double newline
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    text = re.sub(r"[ \t]+", " ", text)

    chunk_size_chars = chunk_size * _CHARS_PER_TOKEN
    overlap_chars = chunk_overlap * _CHARS_PER_TOKEN

    return _split_recursive(text, chunk_size_chars, overlap_chars, _SEPARATORS)


def chunk_document(
    doc: Document,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[Chunk]:
    """
    Split a Document into a list of Chunks, preserving all metadata.

    Args:
        doc: Source Document with content and metadata.
        chunk_size: Target chunk size in tokens.
        chunk_overlap: Token overlap between consecutive chunks.

    Returns:
        List of Chunk objects ready for embedding.
        Empty documents return an empty list (not an error).
    """
    if not doc.content or not doc.content.strip():
        return []

    raw_chunks = chunk_text(doc.content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    total = len(raw_chunks)

    return [
        Chunk(
            text=text,
            source_id=doc.source_id,
            chunk_index=idx,
            total_chunks=total,
            pillar=doc.pillar,
            drug_name=doc.drug_name,
            session_id=doc.session_id,
            metadata={**doc.metadata, "title": doc.title},
        )
        for idx, text in enumerate(raw_chunks)
    ]


def estimate_chunk_count(text: str, chunk_size: int = 512, chunk_overlap: int = 50) -> int:
    """
    Quick estimate of chunk count without full splitting.
    Useful for progress reporting in ingestion tasks.
    """
    if not text:
        return 0
    total_tokens = _approx_tokens(text)
    stride = max(chunk_size - chunk_overlap, 1)
    return max(1, (total_tokens + stride - 1) // stride)
