"""Structure-aware chunking — splits along document sections, not fixed windows.

Each chunk keeps a stable ``clause_id`` derived from ``doc_id + section_path``
so that the same policy clause always produces the same chunk ID regardless
of ingestion order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from claimpilot.rag.models import SourceDoc


@dataclass(frozen=True)
class Chunk:
    """A text chunk with provenance metadata."""

    clause_id: str
    doc_id: str
    title: str
    text: str
    metadata: dict[str, str]


def chunk_document(doc: SourceDoc, *, max_tokens: int = 450, overlap: int = 50) -> list[Chunk]:
    """Split *doc* into structure-aware chunks.

    Strategy:
    1. If *doc.metadata* contains ``section_path``, split on section
       boundaries (lines starting with ``#``-style headings).
    2. Within each section, if the section exceeds *max_tokens* (rough
       word-count proxy), split into sub-chunks with *overlap* word
       overlap so no tail content is dropped.
    3. Each chunk gets a deterministic ``clause_id`` = ``{doc_id}:{section_path}``
       (with a ``:partN`` suffix for sub-chunks).
    """
    sections = _split_sections(doc.text, doc.metadata.get("section_path", ""))
    chunks: list[Chunk] = []

    for section_path, section_text in sections:
        clause_base = f"{doc.doc_id}:{section_path}" if section_path else doc.doc_id
        sub_texts = _split_by_tokens(section_text, max_tokens=max_tokens, overlap=overlap)

        for idx, sub_text in enumerate(sub_texts):
            clause_id = clause_base if len(sub_texts) == 1 else f"{clause_base}:part{idx}"
            chunks.append(
                Chunk(
                    clause_id=clause_id,
                    doc_id=doc.doc_id,
                    title=doc.title,
                    text=sub_text,
                    metadata=doc.metadata,
                )
            )

    return chunks


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)", re.MULTILINE)


def _split_sections(text: str, base_path: str) -> list[tuple[str, str]]:
    """Split *text* on markdown-style headings into ``(section_path, body)``."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [(base_path, text.strip())]

    sections: list[tuple[str, str]] = []

    # Text before the first heading (preamble).
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append((base_path, preamble))

    for i, m in enumerate(matches):
        heading_text = m.group(2).strip()
        path = f"{base_path}/{heading_text}" if base_path else heading_text
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # Prepend the heading so the chunk text includes the section
        # title — important for BM25 matching on clause IDs.
        full_body = f"{heading_text}\n{body}" if body else heading_text
        sections.append((path, full_body))

    return sections


def _split_by_tokens(text: str, *, max_tokens: int, overlap: int) -> list[str]:
    """Split *text* into sub-chunks of roughly *max_tokens* words with overlap."""
    words = text.split()
    if len(words) <= max_tokens:
        return [text]

    parts: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_tokens, len(words))
        parts.append(" ".join(words[start:end]))
        start = end - overlap if end < len(words) else end
    return parts
