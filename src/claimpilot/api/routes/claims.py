"""Claim adjudication routes — master-spec §9."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from claimpilot.api.auth import CallerIdentity, get_caller, require_role
from claimpilot.api.deps import get_claim_store, get_event_bus, get_queue
from claimpilot.api.schemas import (
    ClaimStatusResponse,
    HumanDecisionRequest,
    HumanDecisionResponse,
    SubmitClaimRequest,
    SubmitClaimResponse,
)
from claimpilot.api.worker import ClaimStore, EventBus
from claimpilot.infra.interfaces import Queue, QueueMessage
from claimpilot.models.claim import RawClaim
from claimpilot.models.trace import StepTrace

router = APIRouter(prefix="/v1", tags=["claims"])


# ---------------------------------------------------------------------------
# GET /v1/me — current user + roles (dev-mode stub)
# ---------------------------------------------------------------------------


@router.get("/me")
async def get_me(
    caller: Annotated[CallerIdentity, Depends(get_caller)],
) -> dict[str, object]:
    """Return the current user identity and roles.

    In production, reads from EasyAuth headers (Entra ID).
    In local dev, reads from ``X-Debug-Role`` header (default: adjuster).
    """
    return {"user": caller.user, "roles": caller.roles}


# ---------------------------------------------------------------------------
# GET /v1/claims — list all claims (optionally filter by status)
# ---------------------------------------------------------------------------


@router.get("/claims")
async def list_claims(
    store: Annotated[ClaimStore, Depends(get_claim_store)],
    caller: Annotated[CallerIdentity, Depends(get_caller)],
    status: str | None = None,
) -> list[dict[str, object]]:
    """Return a summary of all tracked claims.

    Filtering by ``status=escalated`` requires the ``admin`` role.
    """
    if status == "escalated" and "admin" not in caller.roles:
        raise HTTPException(status_code=403, detail="Admin role required to list escalated claims.")
    records = await store.list_claims(status=status)
    return [
        {
            "claim_id": r.claim_id,
            "status": r.status,
            "disposition": r.disposition,
            "claimed_amount": str(r.facts_data.get("claimed_amount", "")) if r.facts_data else "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        }
        for r in records
    ]


# ---------------------------------------------------------------------------
# POST /v1/claims — submit
# ---------------------------------------------------------------------------


@router.post("/claims", response_model=SubmitClaimResponse, status_code=202)
async def submit_claim(
    body: SubmitClaimRequest,
    queue: Annotated[Queue, Depends(get_queue)],
    store: Annotated[ClaimStore, Depends(get_claim_store)],
) -> SubmitClaimResponse:
    """Accept a new claim, enqueue for async processing, return claim_id immediately."""
    claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"

    # Persist the initial record so GET works immediately.
    await store.create(claim_id)

    raw = RawClaim(
        claim_id=claim_id,
        policy_number=body.policy_number,
        fnol_text=body.fnol_text,
    )
    await queue.enqueue(
        QueueMessage(
            id=claim_id,
            body={"claim_id": claim_id, "raw_claim": raw.model_dump(mode="json")},
        )
    )

    return SubmitClaimResponse(claim_id=claim_id, status="pending")


# ---------------------------------------------------------------------------
# GET /v1/claims/{claim_id} — status + full outputs
# ---------------------------------------------------------------------------


@router.get("/claims/{claim_id}", response_model=ClaimStatusResponse)
async def get_claim(
    claim_id: str,
    store: Annotated[ClaimStore, Depends(get_claim_store)],
) -> ClaimStatusResponse:
    """Return the current status and all agent outputs for a claim."""
    record = await store.load(claim_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id!r} not found.")

    return ClaimStatusResponse(
        claim_id=record.claim_id,
        status=record.status,
        disposition=record.disposition,
        facts=record.to_facts(),
        policy_context=record.to_policy_context(),
        coverage=record.to_coverage(),
        risk=record.to_risk(),
        settlement=record.to_settlement(),
        compliance=record.to_compliance(),
        trace=record.to_trace(),
        errors=record.to_errors(),
        cost_summary=record.to_cost_summary(),
        human_decision=record.human_decision,
        human_notes=record.human_notes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ---------------------------------------------------------------------------
# GET /v1/claims/{claim_id}/stream — SSE agent steps
# ---------------------------------------------------------------------------


@router.get("/claims/{claim_id}/stream")
async def stream_claim(
    claim_id: str,
    store: Annotated[ClaimStore, Depends(get_claim_store)],
    bus: Annotated[EventBus, Depends(get_event_bus)],
) -> StreamingResponse:
    """Server-Sent Events stream of StepTrace objects as each agent node completes."""
    return StreamingResponse(
        _sse_generator(claim_id, store, bus),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _sse_generator(
    claim_id: str,
    store: ClaimStore,
    bus: EventBus,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted strings for each StepTrace event."""
    # Subscribe BEFORE checking status to avoid the race where the worker
    # completes and publishes the sentinel before we subscribe.
    q = bus.subscribe(claim_id)

    try:
        record = await store.load(claim_id)
        if record is None:
            yield _sse("error", f'{{"detail": "Claim {claim_id!r} not found."}}')
            return

        if record.status in ("completed", "escalated", "error"):
            # Already finished — replay stored trace events.
            bus.unsubscribe(claim_id)
            for trace_data in record.trace_data:
                trace = StepTrace.model_validate(trace_data)
                yield _sse("step", trace.model_dump_json())
            yield _sse("done", f'{{"claim_id": "{claim_id}"}}')
            return

        # Pending / processing — consume live events from the bus.
        # Re-check every 0.5 s in case the worker finished before we subscribed.
        while True:
            try:
                event: StepTrace | None = await asyncio.wait_for(q.get(), timeout=0.5)
            except TimeoutError:
                # Check if the claim finished while we were waiting.
                latest = await store.load(claim_id)
                if latest is not None and latest.status in ("completed", "escalated", "error"):
                    # Missed the sentinel — replay from store.
                    for trace_data in latest.trace_data:
                        trace = StepTrace.model_validate(trace_data)
                        yield _sse("step", trace.model_dump_json())
                    yield _sse("done", f'{{"claim_id": "{claim_id}"}}')
                    return
                continue

            if event is None:
                # Sentinel from worker: processing complete.
                yield _sse("done", f'{{"claim_id": "{claim_id}"}}')
                return

            yield _sse("step", event.model_dump_json())

    finally:
        bus.unsubscribe(claim_id)


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


# ---------------------------------------------------------------------------
# POST /v1/claims/{claim_id}/decision — human approve / deny
# ---------------------------------------------------------------------------


@router.post("/claims/{claim_id}/decision", response_model=HumanDecisionResponse)
async def human_decision(
    claim_id: str,
    body: HumanDecisionRequest,
    store: Annotated[ClaimStore, Depends(get_claim_store)],
    _caller: Annotated[CallerIdentity, Depends(require_role("admin"))],
) -> HumanDecisionResponse:
    """Record a human adjudicator's decision on an escalated claim.

    Transitions the claim from ``escalated`` → ``completed`` with the chosen
    disposition (``auto_approved`` for "approve", ``auto_denied`` for "deny").
    """
    record = await store.load(claim_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id!r} not found.")
    if record.status != "escalated":
        raise HTTPException(
            status_code=409,
            detail=f"Claim {claim_id!r} is not awaiting a decision (status={record.status!r}).",
        )

    record.human_decision = body.decision
    record.human_notes = body.notes
    record.status = "completed"
    record.disposition = "auto_approved" if body.decision == "approve" else "auto_denied"
    await store.save(record)

    return HumanDecisionResponse(
        claim_id=claim_id,
        status="completed",
        disposition=record.disposition,
        human_decision=body.decision,
    )
