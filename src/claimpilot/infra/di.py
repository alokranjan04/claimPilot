"""Dependency-injection factory — wires concrete providers by ``Settings.provider``.

Call ``create_providers(settings)`` to get a ``ProviderSet`` with all seven
infrastructure implementations.  Core code receives these via FastAPI's
dependency injection and never imports a concrete provider directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from claimpilot.infra.interfaces import (
    Checkpointer,
    DocExtractor,
    Embedder,
    LLMClient,
    Queue,
    Reranker,
    VectorStore,
)
from claimpilot.infra.settings import Settings


@dataclass(frozen=True)
class ProviderSet:
    """Immutable bundle of all infrastructure implementations."""

    llm: LLMClient
    embedder: Embedder
    vector_store: VectorStore
    doc_extractor: DocExtractor
    queue: Queue
    checkpointer: Checkpointer
    reranker: Reranker


def create_providers(settings: Settings | None = None) -> ProviderSet:
    """Build and return the full set of providers for the given settings.

    Raises ``NotImplementedError`` for provider values that haven't been
    implemented yet (azure, aws, gcp arrive at later milestones).
    """
    if settings is None:
        settings = Settings()

    if settings.provider == "fake":
        return _create_fake_providers(settings)

    msg = (
        f"Provider {settings.provider!r} is not implemented yet. "
        f"Use PROVIDER=fake for local/test runs."
    )
    raise NotImplementedError(msg)


def _create_fake_providers(settings: Settings) -> ProviderSet:
    from claimpilot.infra.providers.fakes import (
        FakeCheckpointer,
        FakeDocExtractor,
        FakeEmbedder,
        FakeLLMClient,
        FakeQueue,
        FakeReranker,
        FakeVectorStore,
    )

    return ProviderSet(
        llm=FakeLLMClient(seed=settings.fake_seed),
        embedder=FakeEmbedder(dims=settings.embedding_dimensions, seed=settings.fake_seed),
        vector_store=FakeVectorStore(),
        doc_extractor=FakeDocExtractor(),
        queue=FakeQueue(),
        checkpointer=FakeCheckpointer(),
        reranker=FakeReranker(),
    )
