"""Tests for M11 entrypoints: worker_main and ingest_corpus.

Both run against fake providers (no cloud, no API keys).
"""

from __future__ import annotations

import asyncio
import contextlib

from claimpilot.api.worker import ClaimStore, EventBus, run_worker
from claimpilot.api.worker_main import _main as worker_async_main
from claimpilot.graph.build_graph import build_graph
from claimpilot.infra.di import create_providers
from claimpilot.infra.interfaces import QueueMessage
from claimpilot.infra.settings import Settings
from claimpilot.rag.ingest_corpus import _ingest
from claimpilot.rag.pipeline import RagPipeline

# ---------------------------------------------------------------------------
# Worker entrypoint
# ---------------------------------------------------------------------------


class TestWorkerMain:
    """Test that the standalone worker boots and stops cleanly over fakes."""

    async def test_worker_starts_and_cancels(self) -> None:
        """run_worker processes a message and can be cancelled."""
        settings = Settings(provider="fake")
        providers = create_providers(settings)
        graph = build_graph(settings, llm=providers.llm)
        store = ClaimStore(providers.checkpointer)
        bus = EventBus()

        # Enqueue a claim so the worker has something to process.
        await providers.queue.enqueue(
            QueueMessage(
                id="test-msg",
                body={
                    "claim_id": "CLM-TEST-001",
                    "raw_claim": {
                        "claim_id": "CLM-TEST-001",
                        "policy_number": "POL-100",
                        "fnol_text": "Test claim for worker entrypoint.",
                    },
                },
            )
        )

        # Pre-create the claim record (the API route normally does this).
        await store.create("CLM-TEST-001")

        # Start the worker and let it process one message.
        task = asyncio.create_task(run_worker(providers.queue, store, bus, graph))
        # Give it a moment to dequeue and process.
        await asyncio.sleep(0.3)

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        # Verify the claim was processed.
        record = await store.load("CLM-TEST-001")
        assert record is not None
        assert record.status in ("completed", "escalated", "error")

    async def test_worker_main_module_importable(self) -> None:
        """worker_main._main is an async callable."""
        assert asyncio.iscoroutinefunction(worker_async_main)


# ---------------------------------------------------------------------------
# Corpus ingestion job
# ---------------------------------------------------------------------------


class TestIngestCorpus:
    """Test that the ingestion job upserts the demo corpus into the VectorStore."""

    async def test_ingest_populates_vector_store(self) -> None:
        """After ingestion, the fake vector store contains documents."""
        settings = Settings(provider="fake")
        providers = create_providers(settings)

        rag = RagPipeline(
            embedder=providers.embedder,
            vector_store=providers.vector_store,
            reranker=providers.reranker,
            settings=settings,
        )

        from claimpilot.api.main import _DEMO_CORPUS

        await rag.ingest(_DEMO_CORPUS)

        # Search for something that should match.
        embedding = (await providers.embedder.embed(["collision coverage"]))[0]
        hits = await providers.vector_store.search(embedding, top_k=5)
        assert len(hits) > 0

    async def test_ingest_module_importable(self) -> None:
        """ingest_corpus._ingest is an async callable."""
        assert asyncio.iscoroutinefunction(_ingest)
