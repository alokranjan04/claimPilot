"""One-shot corpus ingestion into the configured VectorStore.

Chunks the demo policy corpus, embeds via the configured embedder, and
upserts into the vector store (Azure AI Search when ``PROVIDER=azure``).

Usage::

    python -m claimpilot.rag.ingest_corpus

This replaces the in-memory startup seed used during local dev — after
running this, the AI Search index is populated and the API no longer
needs to re-ingest on every restart.
"""

from __future__ import annotations

import asyncio
import sys

from claimpilot.api.main import _DEMO_CORPUS
from claimpilot.infra.di import create_providers
from claimpilot.infra.settings import Settings
from claimpilot.observability.logging import configure_logging, get_logger
from claimpilot.rag.pipeline import RagPipeline


async def _ingest() -> None:
    configure_logging()
    log = get_logger()

    settings = Settings()
    log.info("ingest_starting", provider=settings.provider, corpus_docs=len(_DEMO_CORPUS))

    providers = create_providers(settings)
    rag = RagPipeline(
        embedder=providers.embedder,
        vector_store=providers.vector_store,
        reranker=providers.reranker,
        settings=settings,
    )

    await rag.ingest(_DEMO_CORPUS)
    log.info("ingest_complete", corpus_docs=len(_DEMO_CORPUS))


def main() -> None:
    """Sync entry point."""
    asyncio.run(_ingest())


if __name__ == "__main__":
    main()
    sys.exit(0)
