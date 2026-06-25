"""RAG-layer data models — typed boundaries for the retrieval pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field

from claimpilot.models.common import Citation


class SourceDoc(BaseModel):
    """A source document to be chunked and ingested."""

    doc_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    metadata: dict[str, str] = {}


class RetrievalFilter(BaseModel):
    """Optional filters passed to ``retrieve``."""

    metadata: dict[str, str] = {}


class RetrievedChunk(BaseModel):
    """A single retrieved passage with its citation and fusion score."""

    citation: Citation
    text: str = Field(min_length=1)
    score: float = Field(ge=0.0)


class RetrievalResult(BaseModel):
    """Output of ``retrieve`` — chunks plus a grounding sufficiency flag."""

    chunks: list[RetrievedChunk] = []
    sufficient: bool = False


class IngestReport(BaseModel):
    """Summary returned after corpus ingestion."""

    docs_ingested: int = 0
    chunks_created: int = 0


class RagNotReadyError(Exception):
    """Raised when ``retrieve`` is called before ``ingest``."""
