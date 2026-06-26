"""GET /v1/evals/latest — return the latest eval scorecard.

Computes on first request (fakes, < 1 s offline) and caches in ``app.state``.
The eval harness lives in ``evals/`` at the project root (outside ``src/``).
We resolve the root at import time and ensure it is on sys.path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/v1/evals", tags=["evals"])

# Make the project root importable so ``import evals`` works when uvicorn
# is started from the repo root (``uv run uvicorn claimpilot.api.main:app``).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@router.get("/latest")
async def get_latest_evals(request: Request) -> dict[str, Any]:
    """Return the latest eval scorecard, computing it on first call."""
    cached: dict[str, Any] | None = getattr(request.app.state, "eval_scorecard", None)
    if cached is not None:
        return cached

    try:
        from evals.metrics import compute_scorecard
        from evals.run_evals import _load_dataset, _run_all

        corpus, cases = _load_dataset()
        results = await _run_all(cases, corpus)
        scorecard = compute_scorecard(results)
        data: dict[str, Any] = scorecard.model_dump(mode="json")
        request.app.state.eval_scorecard = data
        return data
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Evals unavailable: {exc}") from exc
