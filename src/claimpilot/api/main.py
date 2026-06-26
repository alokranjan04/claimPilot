"""FastAPI application entry point — master-spec §9.

The ``create_app()`` factory is the testable unit: it accepts an optional
``LLMClient`` override and RAG corpus so tests can inject scripted responses
without touching the production DI wiring.

``app`` at module level is the standard instance used by uvicorn:
    uv run uvicorn claimpilot.api.main:app --reload
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from claimpilot.api.routes.claims import router as claims_router
from claimpilot.api.routes.evals import router as evals_router
from claimpilot.api.worker import ClaimStore, EventBus, run_worker
from claimpilot.graph.build_graph import build_graph
from claimpilot.infra.di import create_providers
from claimpilot.infra.settings import Settings
from claimpilot.rag.models import SourceDoc
from claimpilot.rag.pipeline import RagPipeline

if TYPE_CHECKING:
    from claimpilot.infra.interfaces import LLMClient

# ---------------------------------------------------------------------------
# Demo policy corpus — ingested at startup so the API can adjudicate claims
# out-of-the-box without any external data store.
# ---------------------------------------------------------------------------

_DEMO_CORPUS: list[SourceDoc] = [
    SourceDoc(
        doc_id="POL-100",
        title="Standard Auto Policy",
        text=(
            "# §1.1 Comprehensive Coverage\n"
            "This section covers damage to the insured vehicle from collisions, "
            "theft, vandalism, weather events, and animal strikes. "
            "The deductible is $500 per incident. Maximum payout is the actual cash value.\n\n"
            "# §1.2 Liability Coverage\n"
            "Covers bodily injury and property damage the insured causes to others. "
            "Minimum limit is $25,000 per occurrence.\n\n"
            "# §1.3 Exclusions\n"
            "Does not cover intentional damage, racing, or commercial use of the insured vehicle."
        ),
        metadata={"jurisdiction": "IL", "policy_type": "auto"},
    ),
]


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    rag_corpus: list[SourceDoc] | None = None,
) -> FastAPI:
    """Build a FastAPI application.

    Parameters
    ----------
    settings:
        App settings; defaults used when ``None``.
    llm:
        Override the LLM client (used by tests to inject scripted responses).
    rag_corpus:
        Policy documents to ingest at startup; defaults to the demo corpus.
    """
    _settings = settings or Settings()
    _corpus = rag_corpus if rag_corpus is not None else _DEMO_CORPUS

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        providers = create_providers(_settings)
        _llm = llm or providers.llm

        rag = RagPipeline(
            embedder=providers.embedder,
            vector_store=providers.vector_store,
            reranker=providers.reranker,
            settings=_settings,
        )
        await rag.ingest(_corpus)

        graph = build_graph(_settings, llm=_llm, rag=rag)

        store = ClaimStore(providers.checkpointer)
        bus = EventBus()

        # Expose shared objects to route handlers via app.state.
        app.state.settings = _settings
        app.state.queue = providers.queue
        app.state.store = store
        app.state.bus = bus

        worker_task = asyncio.create_task(run_worker(providers.queue, store, bus, graph))

        yield

        worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await worker_task

    _app = FastAPI(
        title="ClaimPilot",
        description="Autonomous insurance claims adjudication API.",
        version="0.1.0",
        lifespan=lifespan,
    )

    _app.include_router(claims_router)
    _app.include_router(evals_router)

    @_app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    @_app.get("/readyz", tags=["ops"])
    async def readyz() -> JSONResponse:
        """Readiness probe."""
        return JSONResponse(content={"status": "ready"})

    return _app


# ---------------------------------------------------------------------------
# Default application instance (used by uvicorn)
# ---------------------------------------------------------------------------

app = create_app()
