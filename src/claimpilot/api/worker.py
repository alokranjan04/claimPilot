"""Background worker, claim store, and SSE event bus.

Architecture (master-spec §10):
  - ClaimStore  — CRUD over the Checkpointer interface; holds ClaimRecord snapshots.
  - EventBus    — per-claim asyncio.Queue for streaming StepTrace events to SSE.
  - run_worker  — consumes the Queue, runs the graph, writes to store + bus.

M9 additions:
  - ``ClaimRecord.cost_summary_data`` persists the per-claim cost/latency summary.
  - ``_process_claim`` calls ``compute_cost_summary`` after graph completion and
    emits structured log records (no PII) via ``get_logger``.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any, Literal

from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from claimpilot.infra.interfaces import Checkpointer, Queue
from claimpilot.models.claim import ClaimFacts, RawClaim
from claimpilot.models.decisions import (
    ComplianceVerdict,
    CoverageOpinion,
    PolicyContext,
    RiskAssessment,
    SettlementProposal,
)
from claimpilot.models.trace import AgentError, StepTrace
from claimpilot.observability.cost_meter import ClaimCostSummary, compute_cost_summary
from claimpilot.observability.logging import get_logger

# ---------------------------------------------------------------------------
# Persisted claim record (stored in the Checkpointer)
# ---------------------------------------------------------------------------


class ClaimRecord(BaseModel):
    """Snapshot of a claim's state, persisted via the Checkpointer interface."""

    claim_id: str
    status: Literal["pending", "processing", "completed", "escalated", "error"]
    disposition: str | None = None

    # Agent outputs serialised as plain dicts (Decimal → str in JSON mode)
    facts_data: dict[str, Any] | None = None
    policy_context_data: dict[str, Any] | None = None
    coverage_data: dict[str, Any] | None = None
    risk_data: dict[str, Any] | None = None
    settlement_data: dict[str, Any] | None = None
    compliance_data: dict[str, Any] | None = None

    trace_data: list[dict[str, Any]] = Field(default_factory=list)
    errors_data: list[dict[str, Any]] = Field(default_factory=list)

    # M9: per-claim cost/latency summary
    cost_summary_data: dict[str, Any] | None = None

    # Human-in-the-loop fields
    human_decision: str | None = None
    human_notes: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    # ---------------------------------------------------------------------------
    # Reconstruction helpers
    # ---------------------------------------------------------------------------

    def to_facts(self) -> ClaimFacts | None:
        return ClaimFacts.model_validate(self.facts_data) if self.facts_data else None

    def to_policy_context(self) -> PolicyContext | None:
        if self.policy_context_data is None:
            return None
        return PolicyContext.model_validate(self.policy_context_data)

    def to_coverage(self) -> CoverageOpinion | None:
        return CoverageOpinion.model_validate(self.coverage_data) if self.coverage_data else None

    def to_risk(self) -> RiskAssessment | None:
        return RiskAssessment.model_validate(self.risk_data) if self.risk_data else None

    def to_settlement(self) -> SettlementProposal | None:
        if self.settlement_data is None:
            return None
        return SettlementProposal.model_validate(self.settlement_data)

    def to_compliance(self) -> ComplianceVerdict | None:
        if self.compliance_data is None:
            return None
        return ComplianceVerdict.model_validate(self.compliance_data)

    def to_trace(self) -> list[StepTrace]:
        return [StepTrace.model_validate(t) for t in self.trace_data]

    def to_errors(self) -> list[AgentError]:
        return [AgentError.model_validate(e) for e in self.errors_data]

    def to_cost_summary(self) -> ClaimCostSummary | None:
        if self.cost_summary_data is None:
            return None
        return ClaimCostSummary.model_validate(self.cost_summary_data)


# ---------------------------------------------------------------------------
# ClaimStore — thin CRUD layer over the Checkpointer
# ---------------------------------------------------------------------------

_KEY_PREFIX = "claim:"


class ClaimStore:
    """Persist and retrieve :class:`ClaimRecord` objects via the Checkpointer."""

    def __init__(self, checkpointer: Checkpointer) -> None:
        self._cp = checkpointer

    def _key(self, claim_id: str) -> str:
        return f"{_KEY_PREFIX}{claim_id}"

    async def create(self, claim_id: str) -> ClaimRecord:
        record = ClaimRecord(claim_id=claim_id, status="pending")
        await self._cp.save(self._key(claim_id), record.model_dump(mode="json"))
        return record

    async def load(self, claim_id: str) -> ClaimRecord | None:
        data = await self._cp.load(self._key(claim_id))
        if data is None:
            return None
        return ClaimRecord.model_validate(data)

    async def save(self, record: ClaimRecord) -> None:
        record.updated_at = datetime.now(tz=UTC)
        await self._cp.save(self._key(record.claim_id), record.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# EventBus — per-claim asyncio.Queue for live SSE streaming
# ---------------------------------------------------------------------------


class EventBus:
    """Routes StepTrace events from the worker to SSE subscribers.

    The worker publishes events as each graph node completes.
    The SSE handler subscribes, consumes events, and forwards them to clients.
    A ``None`` sentinel signals end-of-stream.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[StepTrace | None]] = {}

    def subscribe(self, claim_id: str) -> asyncio.Queue[StepTrace | None]:
        """Return (or create) the per-claim event queue."""
        if claim_id not in self._queues:
            self._queues[claim_id] = asyncio.Queue()
        return self._queues[claim_id]

    async def publish(self, claim_id: str, event: StepTrace | None) -> None:
        """Put an event onto the per-claim queue (no-op if no subscriber)."""
        q = self._queues.get(claim_id)
        if q is not None:
            await q.put(event)

    def unsubscribe(self, claim_id: str) -> None:
        self._queues.pop(claim_id, None)


# ---------------------------------------------------------------------------
# Worker — consumes the Queue and runs the graph
# ---------------------------------------------------------------------------


async def run_worker(
    queue: Queue,
    store: ClaimStore,
    bus: EventBus,
    graph: CompiledStateGraph,  # type: ignore[type-arg]
) -> None:
    """Background worker loop: dequeue → process claim → save.

    Runs until cancelled (CancelledError propagates out of ``queue.dequeue``).
    """
    while True:
        msg = await queue.dequeue(timeout_seconds=0.5)
        if msg is None:
            continue

        body = msg.body
        claim_id: str = body["claim_id"]
        raw_claim = RawClaim.model_validate(body["raw_claim"])

        try:
            await _process_claim(claim_id, raw_claim, graph, store, bus)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record = await store.load(claim_id)
            if record is not None:
                record.status = "error"
                record.errors_data = [
                    {
                        "node": "worker",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                ]
                await store.save(record)
            await bus.publish(claim_id, None)  # sentinel: unblock waiting SSE clients
        finally:
            with contextlib.suppress(Exception):
                await queue.ack(msg.id)


async def _process_claim(
    claim_id: str,
    raw_claim: RawClaim,
    graph: CompiledStateGraph,  # type: ignore[type-arg]
    store: ClaimStore,
    bus: EventBus,
) -> None:
    """Run one claim through the graph, streaming events and saving final state."""
    log = get_logger(claim_id)
    record = await store.load(claim_id)
    if record is None:
        return

    record.status = "processing"
    await store.save(record)
    log.info("claim_processing_started", node="worker")

    final_state: dict[str, Any] | None = None
    prev_trace_len = 0

    # stream_mode="values" yields the full accumulated state after each node.
    async for state in graph.astream(
        {"claim_id": claim_id, "raw_input": raw_claim},
        stream_mode="values",
    ):
        current_traces: list[StepTrace] = state.get("trace", [])
        for trace in current_traces[prev_trace_len:]:
            await bus.publish(claim_id, trace)
        prev_trace_len = len(current_traces)
        final_state = state

    # Sentinel: signal end-of-stream to SSE subscribers.
    await bus.publish(claim_id, None)

    if final_state is None:
        record.status = "error"
        await store.save(record)
        return

    # Persist the final state.
    disp: str | None = final_state.get("disposition")
    record.disposition = disp
    record.status = "escalated" if disp == "escalated" else "completed"

    if final_state.get("facts") is not None:
        record.facts_data = final_state["facts"].model_dump(mode="json")
    if final_state.get("policy_context") is not None:
        record.policy_context_data = final_state["policy_context"].model_dump(mode="json")
    if final_state.get("coverage") is not None:
        record.coverage_data = final_state["coverage"].model_dump(mode="json")
    if final_state.get("risk") is not None:
        record.risk_data = final_state["risk"].model_dump(mode="json")
    if final_state.get("settlement") is not None:
        record.settlement_data = final_state["settlement"].model_dump(mode="json")
    if final_state.get("compliance") is not None:
        record.compliance_data = final_state["compliance"].model_dump(mode="json")

    trace_list: list[StepTrace] = final_state.get("trace", [])
    record.trace_data = [t.model_dump(mode="json") for t in trace_list]
    record.errors_data = [e.model_dump(mode="json") for e in final_state.get("errors", [])]

    # M9: compute and persist cost/latency summary.
    summary = compute_cost_summary(claim_id, trace_list)
    record.cost_summary_data = summary.model_dump(mode="json")

    await store.save(record)
    log.info(
        "claim_processing_completed",
        disposition=disp,
        node_count=summary.node_count,
        total_latency_ms=summary.total_latency_ms,
        total_cost_usd=str(summary.total_cost_usd),
    )
