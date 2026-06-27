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
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

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
    SourceDoc(
        doc_id="POL-200",
        title="Homeowner's Insurance Policy",
        text=(
            "# §2.1 Dwelling Coverage\n"
            "Covers damage to the insured dwelling from fire, lightning, windstorm, hail, "
            "explosion, smoke, vandalism, theft, and water damage from burst pipes or "
            "accidental overflow. The deductible is $1,000 per incident. Coverage limit "
            "is the dwelling replacement cost stated on the declarations page.\n\n"
            "# §2.2 Personal Property Coverage\n"
            "Covers loss or damage to personal belongings inside the dwelling, including "
            "furniture, electronics, clothing, and appliances. Sub-limit of $2,500 for "
            "jewelry, watches, and furs. Coverage is actual cash value unless replacement "
            "cost endorsement is purchased.\n\n"
            "# §2.3 Loss of Use Coverage\n"
            "If the dwelling is uninhabitable due to a covered peril, pays reasonable "
            "additional living expenses (hotel, meals, temporary rental) for up to "
            "12 months or 20% of the dwelling coverage limit, whichever is less.\n\n"
            "# §2.4 Liability Coverage\n"
            "Covers bodily injury or property damage to third parties occurring on the "
            "insured premises. Minimum limit is $100,000 per occurrence. Includes legal "
            "defense costs. Does not cover intentional acts or business activities.\n\n"
            "# §2.5 Exclusions\n"
            "Does not cover: flood damage (requires separate flood policy), earthquake, "
            "gradual deterioration or wear and tear, mold (unless resulting from a covered "
            "peril), pest or vermin damage, intentional damage by the insured, or damage "
            "from failure to maintain the property."
        ),
        metadata={"jurisdiction": "IL", "policy_type": "homeowner"},
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

    # Serve the Claims Console UI at / (after API routes so /v1/* wins).
    _ui_dir = Path(__file__).resolve().parent.parent.parent.parent / "ui"
    if _ui_dir.is_dir():
        _app.mount("/", StaticFiles(directory=str(_ui_dir), html=True), name="ui")

    return _app


# ---------------------------------------------------------------------------
# Default application instance (used by uvicorn)
# ---------------------------------------------------------------------------

app = create_app()
