"""Provider interfaces — the abstraction boundary between core and infrastructure.

Every concrete provider (fake, Azure, AWS, GCP) implements these protocols.
Core code (agents, graph, RAG) depends *only* on these protocols and is
wired to concrete implementations via the DI factory in ``di.py``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMClient(Protocol):
    """Send a prompt to an LLM and receive structured or plain-text output."""

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_schema: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        """Return a dict of the model response.

        If *response_schema* is given the provider must return a dict that
        validates against that Pydantic model (structured-output mode).

        Keys guaranteed in the returned dict:
        - ``"content"`` — the textual or JSON payload.
        - ``"usage"`` — ``{"prompt_tokens": int, "completion_tokens": int}``.
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


@runtime_checkable
class Embedder(Protocol):
    """Produce dense vector embeddings for text passages."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...  # pragma: no cover

    @property
    def dimensions(self) -> int:
        """Dimensionality of the vectors produced by this embedder."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------------


class VectorRecord(BaseModel):
    """A document chunk stored in the vector store."""

    id: str
    text: str
    embedding: list[float]
    metadata: dict[str, str] = {}


class SearchHit(BaseModel):
    """A single result returned from a vector similarity search.

    Named ``SearchHit`` (not ``RetrievalResult``) to avoid confusion with
    the RAG-layer's higher-level ``RetrievalResult`` which carries citations
    and sufficiency judgements.
    """

    id: str
    text: str
    score: float
    metadata: dict[str, str] = {}


@runtime_checkable
class VectorStore(Protocol):
    """Persist and query dense-vector document chunks."""

    async def upsert(self, records: list[VectorRecord]) -> None:
        """Insert or update records."""
        ...  # pragma: no cover

    async def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        filter_metadata: dict[str, str] | None = None,
    ) -> list[SearchHit]:
        """Return the *top_k* most similar records."""
        ...  # pragma: no cover

    async def delete(self, ids: list[str]) -> None:
        """Remove records by id."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------


@runtime_checkable
class Reranker(Protocol):
    """Re-score and re-order candidate search hits for precision.

    In production this wraps a cross-encoder or a service like Azure AI
    Search semantic ranker.  The fake is an identity/no-op pass-through.
    """

    async def rerank(
        self,
        query: str,
        hits: list[SearchHit],
        *,
        top_k: int = 5,
    ) -> list[SearchHit]:
        """Return *hits* re-scored and truncated to *top_k*."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Document extraction
# ---------------------------------------------------------------------------


class ExtractedDocument(BaseModel):
    """Structured output from a document extractor."""

    text: str
    pages: int
    # Any justified: extractor metadata varies by provider/format.
    metadata: dict[str, Any] = {}


@runtime_checkable
class DocExtractor(Protocol):
    """Extract text + metadata from binary documents (PDFs, images, etc.)."""

    async def extract(self, content: bytes, *, content_type: str) -> ExtractedDocument:
        """Parse *content* and return extracted text."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


class QueueMessage(BaseModel):
    """Wrapper around a queued payload with metadata."""

    id: str
    body: dict[str, Any]  # Any justified: queue payload is heterogeneous JSON.


@runtime_checkable
class Queue(Protocol):
    """Async job queue for claim processing."""

    async def enqueue(self, message: QueueMessage) -> None:
        """Put a message onto the queue."""
        ...  # pragma: no cover

    async def dequeue(self, *, timeout_seconds: float = 30.0) -> QueueMessage | None:
        """Consume the next message, or ``None`` if the timeout elapses."""
        ...  # pragma: no cover

    async def ack(self, message_id: str) -> None:
        """Acknowledge successful processing of a message."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Checkpointer
# ---------------------------------------------------------------------------


@runtime_checkable
class Checkpointer(Protocol):
    """Persist and restore graph state snapshots for pause/resume."""

    async def save(self, key: str, state: dict[str, Any]) -> None:
        """Persist *state* under *key* (typically the claim_id)."""
        ...  # pragma: no cover

    async def load(self, key: str) -> dict[str, Any] | None:
        """Return the saved state or ``None`` if not found."""
        ...  # pragma: no cover

    async def delete(self, key: str) -> None:
        """Remove a checkpoint."""
        ...  # pragma: no cover
