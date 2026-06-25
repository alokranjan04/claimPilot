"""Deterministic in-memory fakes — no network, no API keys required.

Every fake is seeded for reproducibility and implements the corresponding
protocol from ``claimpilot.infra.interfaces``.
"""

from claimpilot.infra.providers.fakes.checkpointer import FakeCheckpointer
from claimpilot.infra.providers.fakes.doc_extractor import FakeDocExtractor
from claimpilot.infra.providers.fakes.embedder import FakeEmbedder
from claimpilot.infra.providers.fakes.llm import FakeLLMClient
from claimpilot.infra.providers.fakes.queue import FakeQueue
from claimpilot.infra.providers.fakes.reranker import FakeReranker
from claimpilot.infra.providers.fakes.vector_store import FakeVectorStore

__all__ = [
    "FakeCheckpointer",
    "FakeDocExtractor",
    "FakeEmbedder",
    "FakeLLMClient",
    "FakeQueue",
    "FakeReranker",
    "FakeVectorStore",
]
