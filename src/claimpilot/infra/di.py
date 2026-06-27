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
    implemented yet (aws, gcp arrive at later milestones).
    Raises ``ImportError`` if ``PROVIDER=azure`` but the azure extra is not
    installed (``uv sync --extra azure``).
    """
    if settings is None:
        settings = Settings()

    if settings.provider == "fake":
        return _create_fake_providers(settings)

    if settings.provider == "azure":
        return _create_azure_providers(settings)

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


def _create_azure_providers(settings: Settings) -> ProviderSet:
    """Wire all seven Azure providers from settings.

    Raises ``ImportError`` if the ``azure`` extra is not installed.
    """
    from claimpilot.infra.providers.azure import (
        AzureCosmosCheckpointer,
        AzureDocumentIntelligenceExtractor,
        AzureOpenAIEmbedder,
        AzureOpenAILLMClient,
        AzureSearchReranker,
        AzureSearchVectorStore,
        AzureServiceBusQueue,
    )

    return ProviderSet(
        llm=AzureOpenAILLMClient(
            endpoint=settings.aoai_endpoint,
            deployment=settings.aoai_deployment_chat,
            api_version=settings.aoai_api_version,
        ),
        embedder=AzureOpenAIEmbedder(
            endpoint=settings.aoai_endpoint,
            deployment=settings.aoai_deployment_embedding,
            api_version=settings.aoai_api_version,
            dims=settings.embedding_dimensions,
        ),
        vector_store=AzureSearchVectorStore(
            endpoint=settings.azure_search_endpoint,
            index_name=settings.azure_search_index,
            embedding_dimensions=settings.embedding_dimensions,
        ),
        doc_extractor=AzureDocumentIntelligenceExtractor(
            endpoint=settings.azure_docintel_endpoint,
        ),
        queue=AzureServiceBusQueue(
            namespace=settings.azure_servicebus_namespace,
            queue_name=settings.azure_servicebus_queue,
        ),
        checkpointer=AzureCosmosCheckpointer(
            endpoint=settings.azure_cosmos_endpoint,
            database=settings.azure_cosmos_database,
            container=settings.azure_cosmos_container,
        ),
        reranker=AzureSearchReranker(
            endpoint=settings.azure_search_endpoint,
            index_name=settings.azure_search_index,
            semantic_config=settings.azure_search_semantic_config,
        ),
    )
