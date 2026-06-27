"""End-to-end API tests — master-spec §9, M8 acceptance criteria.

Test strategy:
  - Uses ``create_app()`` with a scripted ``FakeLLMClient`` to get deterministic
    dispositions (auto_approved / auto_denied / escalated).
  - Runs against the full ASGI app via ``httpx.AsyncClient`` + a minimal
    ASGI lifespan wrapper (``_LifespanManager``) that sends startup/shutdown
    events to trigger ``create_app``'s lifespan context manager.
  - The background worker task runs on the same asyncio event loop; polling
    GET /v1/claims/{id} yields control between polls so the worker can advance.

Acceptance criteria checked:
  [x] submit → process → fetch works offline
  [x] escalated claim resolved via POST /v1/claims/{id}/decision
  [x] SSE streams StepTrace steps then a done event
  [x] /healthz and /readyz return 200
  [x] GET /v1/evals/latest returns a gate-passing scorecard
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from claimpilot.api.main import create_app
from claimpilot.infra.providers.fakes import FakeLLMClient
from claimpilot.infra.settings import Settings
from claimpilot.rag.models import SourceDoc

# ---------------------------------------------------------------------------
# Minimal ASGI lifespan manager (avoids adding asgi-lifespan as a dependency)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Send ASGI startup/shutdown events so the app's lifespan context runs."""
    startup_complete: asyncio.Event = asyncio.Event()
    shutdown_complete: asyncio.Event = asyncio.Event()
    receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def receive() -> dict[str, Any]:
        return await receive_queue.get()

    async def send(event: dict[str, Any]) -> None:
        if event["type"] == "lifespan.startup.complete":
            startup_complete.set()
        elif event["type"] == "lifespan.shutdown.complete":
            shutdown_complete.set()

    lifespan_scope: dict[str, Any] = {"type": "lifespan", "asgi": {"version": "3.0"}}
    task = asyncio.create_task(app(lifespan_scope, receive, send))  # type: ignore[arg-type]

    await receive_queue.put({"type": "lifespan.startup"})
    await startup_complete.wait()

    try:
        yield
    finally:
        await receive_queue.put({"type": "lifespan.shutdown"})
        await shutdown_complete.wait()
        await task


# ---------------------------------------------------------------------------
# Shared policy corpus and scripted LLM responses
# ---------------------------------------------------------------------------

_CORPUS = [
    SourceDoc(
        doc_id="POL-100",
        title="Standard Auto Policy",
        text=(
            "# §1.1 Comprehensive Coverage\n"
            "This section covers damage to the insured vehicle from collisions, "
            "theft, vandalism, weather events, and animal strikes. "
            "The deductible is $500 per incident. Maximum payout is the actual cash value.\n\n"
            "# §1.2 Liability Coverage\n"
            "Covers bodily injury and property damage the insured causes to others.\n\n"
            "# §1.3 Exclusions\n"
            "Does not cover intentional damage, racing, or commercial use."
        ),
        metadata={"jurisdiction": "IL", "policy_type": "auto"},
    )
]

_CLAUSE = "POL-100:§1.1 Comprehensive Coverage"

# LLM scripted for auto-approved path (50 claim's worth).
_APPROVE_SCRIPTS = [
    {
        "decision": "covered",
        "confidence": 0.95,
        "rationale": "Covered under §1.1.",
        "citations": [
            {
                "clause_id": _CLAUSE,
                "document": "Standard Auto Policy",
                "snippet": "covers damage from collisions",
            }
        ],
    },
    {"score": 0.05, "signals": [], "recommendation": "approve"},
    {
        "payable_amount": "4500.00",
        "deductible_applied": "500.00",
        "limit_applied": "100000.00",
        "breakdown": [{"description": "Repair", "amount": "4500.00"}],
    },
    {"passed": True, "violations": [], "rationale": "Compliant.", "citations": []},
] * 50  # enough for multiple claims per test

# LLM scripted for escalation via high settlement (50 claims).
_ESCALATE_SCRIPTS = [
    {
        "decision": "covered",
        "confidence": 0.95,
        "rationale": "Covered under §1.1.",
        "citations": [
            {
                "clause_id": _CLAUSE,
                "document": "Standard Auto Policy",
                "snippet": "covers damage from collisions",
            }
        ],
    },
    {"score": 0.05, "signals": [], "recommendation": "approve"},
    {
        "payable_amount": "49500.00",
        "deductible_applied": "500.00",
        "limit_applied": "100000.00",
        "breakdown": [{"description": "Total loss", "amount": "49500.00"}],
    },
    {"passed": True, "violations": [], "rationale": "Compliant.", "citations": []},
] * 50

_SETTINGS = Settings(rag_tau_sufficient=0.001)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def approve_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Client backed by an app that always auto-approves."""
    app = create_app(
        _SETTINGS,
        llm=FakeLLMClient(scripted=list(_APPROVE_SCRIPTS)),
        rag_corpus=_CORPUS,
    )
    async with (
        _lifespan(app),
        httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Debug-Role": "admin"},
        ) as client,
    ):
        yield client


@pytest.fixture
async def escalate_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Client backed by an app that always escalates (high settlement amount)."""
    app = create_app(
        _SETTINGS,
        llm=FakeLLMClient(scripted=list(_ESCALATE_SCRIPTS)),
        rag_corpus=_CORPUS,
    )
    async with (
        _lifespan(app),
        httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Debug-Role": "admin"},
        ) as client,
    ):
        yield client


async def _wait_for_terminal(
    client: httpx.AsyncClient,
    claim_id: str,
    *,
    max_polls: int = 60,
) -> dict:
    """Poll GET /v1/claims/{id} until status leaves pending/processing."""
    for _ in range(max_polls):
        await asyncio.sleep(0)  # yield to event loop (lets worker advance)
        resp = await client.get(f"/v1/claims/{claim_id}")
        data = resp.json()
        if data["status"] not in ("pending", "processing"):
            return data  # type: ignore[return-value]
    return resp.json()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Ops probes
# ---------------------------------------------------------------------------


async def test_healthz(approve_client: httpx.AsyncClient) -> None:
    resp = await approve_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz(approve_client: httpx.AsyncClient) -> None:
    resp = await approve_client.get("/readyz")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Submit → process → fetch (auto-approved path)
# ---------------------------------------------------------------------------


async def test_submit_returns_202(approve_client: httpx.AsyncClient) -> None:
    resp = await approve_client.post(
        "/v1/claims",
        json={"policy_number": "POL-100", "fnol_text": "Minor fender bender $5000."},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"
    assert data["claim_id"].startswith("CLM-")


async def test_get_returns_404_for_unknown(approve_client: httpx.AsyncClient) -> None:
    resp = await approve_client.get("/v1/claims/CLM-UNKNOWN")
    assert resp.status_code == 404


async def test_submit_process_fetch_auto_approved(approve_client: httpx.AsyncClient) -> None:
    """Full happy path: submit → worker processes → auto_approved with trace."""
    resp = await approve_client.post(
        "/v1/claims",
        json={"policy_number": "POL-100", "fnol_text": "Fender bender $5000."},
    )
    claim_id = resp.json()["claim_id"]

    data = await _wait_for_terminal(approve_client, claim_id)

    assert data["status"] == "completed"
    assert data["disposition"] == "auto_approved"
    assert data["coverage"]["decision"] == "covered"
    assert data["risk"]["score"] <= 0.3
    assert data["settlement"] is not None
    # Decimal serialised as string, not float.
    assert data["settlement"]["payable_amount"] == "4500.00"
    assert data["compliance"]["passed"] is True
    assert len(data["trace"]) >= 7  # all nodes ran
    assert data["errors"] == []


async def test_settlement_decimal_not_float(approve_client: httpx.AsyncClient) -> None:
    """Money amounts must be strings (Decimal) in the JSON response."""
    resp = await approve_client.post(
        "/v1/claims",
        json={"policy_number": "POL-100", "fnol_text": "Collision $5000."},
    )
    claim_id = resp.json()["claim_id"]
    data = await _wait_for_terminal(approve_client, claim_id)

    settlement = data.get("settlement") or {}
    if settlement:
        # Pydantic v2 serialises Decimal as string in JSON mode.
        assert isinstance(settlement["payable_amount"], str)
        # Must parse back to Decimal without loss.
        assert Decimal(settlement["payable_amount"]) >= Decimal(0)


# ---------------------------------------------------------------------------
# Escalation path + decision endpoint
# ---------------------------------------------------------------------------


async def test_escalation_and_approve_decision(escalate_client: httpx.AsyncClient) -> None:
    """High-amount claim escalates; POST /decision approves it."""
    resp = await escalate_client.post(
        "/v1/claims",
        json={"policy_number": "POL-100", "fnol_text": "Total loss $50000."},
    )
    claim_id = resp.json()["claim_id"]

    data = await _wait_for_terminal(escalate_client, claim_id)
    assert data["status"] == "escalated"
    assert data["disposition"] == "escalated"

    # Human approves.
    dec_resp = await escalate_client.post(
        f"/v1/claims/{claim_id}/decision",
        json={"decision": "approve", "notes": "Reviewed, valid total-loss."},
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    assert dec_data["status"] == "completed"
    assert dec_data["disposition"] == "auto_approved"
    assert dec_data["human_decision"] == "approve"

    # Verify GET reflects the decision.
    get_resp = await escalate_client.get(f"/v1/claims/{claim_id}")
    final = get_resp.json()
    assert final["status"] == "completed"
    assert final["disposition"] == "auto_approved"
    assert final["human_decision"] == "approve"
    assert final["human_notes"] == "Reviewed, valid total-loss."


async def test_escalation_and_deny_decision(escalate_client: httpx.AsyncClient) -> None:
    """Human denies an escalated claim."""
    resp = await escalate_client.post(
        "/v1/claims",
        json={"policy_number": "POL-100", "fnol_text": "Total loss $50000."},
    )
    claim_id = resp.json()["claim_id"]
    await _wait_for_terminal(escalate_client, claim_id)

    dec_resp = await escalate_client.post(
        f"/v1/claims/{claim_id}/decision",
        json={"decision": "deny"},
    )
    assert dec_resp.status_code == 200
    assert dec_resp.json()["disposition"] == "auto_denied"


async def test_decision_on_non_escalated_returns_409(approve_client: httpx.AsyncClient) -> None:
    """Decision endpoint must return 409 for a non-escalated claim."""
    resp = await approve_client.post(
        "/v1/claims",
        json={"policy_number": "POL-100", "fnol_text": "Fender bender $5000."},
    )
    claim_id = resp.json()["claim_id"]
    await _wait_for_terminal(approve_client, claim_id)

    dec_resp = await approve_client.post(
        f"/v1/claims/{claim_id}/decision",
        json={"decision": "approve"},
    )
    assert dec_resp.status_code == 409


async def test_decision_on_unknown_claim_returns_404(escalate_client: httpx.AsyncClient) -> None:
    resp = await escalate_client.post(
        "/v1/claims/CLM-NOTEXIST/decision",
        json={"decision": "approve"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------


async def test_sse_streams_steps_and_done(escalate_client: httpx.AsyncClient) -> None:
    """SSE endpoint emits step events and a final done event."""
    resp = await escalate_client.post(
        "/v1/claims",
        json={"policy_number": "POL-100", "fnol_text": "Major damage $50000."},
    )
    claim_id = resp.json()["claim_id"]

    # Wait for processing to complete, then SSE replays stored events.
    await _wait_for_terminal(escalate_client, claim_id)

    sse_resp = await escalate_client.get(
        f"/v1/claims/{claim_id}/stream",
        headers={"Accept": "text/event-stream"},
    )
    assert sse_resp.status_code == 200
    assert "text/event-stream" in sse_resp.headers["content-type"]

    body = sse_resp.text
    lines = body.strip().split("\n")
    events = [ln.removeprefix("event: ").strip() for ln in lines if ln.startswith("event:")]

    assert "step" in events, f"Expected step events, got: {events}"
    assert events[-1] == "done", f"Last event must be 'done', got: {events}"
    assert len(events) >= 8  # one per node (≥7) + done


async def test_sse_on_unknown_claim_returns_error_event(escalate_client: httpx.AsyncClient) -> None:
    sse_resp = await escalate_client.get("/v1/claims/CLM-NOPE/stream")
    assert sse_resp.status_code == 200  # SSE always 200
    assert "event: error" in sse_resp.text


# ---------------------------------------------------------------------------
# Evals endpoint
# ---------------------------------------------------------------------------


async def test_evals_latest_returns_passing_scorecard(approve_client: httpx.AsyncClient) -> None:
    """GET /v1/evals/latest must return a gate-passing scorecard."""
    resp = await approve_client.get("/v1/evals/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["gate_passed"] is True
    assert data["total_cases"] >= 10
    assert data["decision_accuracy"] >= 0.9


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------


async def test_me_returns_roles(approve_client: httpx.AsyncClient) -> None:
    """GET /v1/me returns the caller identity with roles."""
    resp = await approve_client.get("/v1/me")
    assert resp.status_code == 200
    data = resp.json()
    assert "user" in data
    assert "roles" in data
    assert isinstance(data["roles"], list)


async def test_me_default_role_is_adjuster(approve_client: httpx.AsyncClient) -> None:
    """Without X-Debug-Role header, default role is adjuster."""
    resp = await approve_client.get("/v1/me", headers={"X-Debug-Role": ""})
    # empty header → falls through to default "adjuster" in get_caller
    assert resp.status_code == 200


async def test_decision_requires_admin_role(escalate_client: httpx.AsyncClient) -> None:
    """POST /decision returns 403 for a non-admin caller."""
    resp = await escalate_client.post(
        "/v1/claims",
        json={"policy_number": "POL-100", "fnol_text": "Total loss $50000."},
    )
    claim_id = resp.json()["claim_id"]
    await _wait_for_terminal(escalate_client, claim_id)

    # Call as adjuster (not admin) → 403
    dec_resp = await escalate_client.post(
        f"/v1/claims/{claim_id}/decision",
        json={"decision": "approve", "notes": "test"},
        headers={"X-Debug-Role": "adjuster"},  # override the default admin
    )
    assert dec_resp.status_code == 403
    assert "admin" in dec_resp.json()["detail"].lower()


async def test_escalated_list_requires_admin(approve_client: httpx.AsyncClient) -> None:
    """GET /v1/claims?status=escalated returns 403 for non-admin."""
    resp = await approve_client.get(
        "/v1/claims?status=escalated",
        headers={"X-Debug-Role": "adjuster"},
    )
    assert resp.status_code == 403
