"""Build the LangGraph state machine for claim adjudication.

Topology per master-spec §5::

    START → intake → policy_retrieval → coverage_decision → fraud_risk
          → settlement → compliance → route
    route ──(auto)──▶ finalize_auto → END
    route ──(escalate)──▶ human_escalation → END
    route ──(errors)──▶ error_handler → human_escalation → END

M9 observability additions:
  - Every node is wrapped by ``_safe`` (async, error-catching) or ``_timed``
    (sync, pass-through) to measure latency, patch ``StepTrace.latency_ms``,
    and emit a :class:`~claimpilot.observability.tracer.SpanData` record via
    the injected ``SpanExporter``.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from claimpilot.graph import nodes
from claimpilot.graph.state import GraphState
from claimpilot.infra.interfaces import LLMClient
from claimpilot.infra.settings import Settings
from claimpilot.mcp_servers.claims_history import ClaimsHistoryServer
from claimpilot.mcp_servers.fraud_signals import FraudSignalsServer
from claimpilot.mcp_servers.regs import RegsServer
from claimpilot.models.trace import AgentError, StepTrace
from claimpilot.observability.tracer import NoOpSpanExporter, SpanData, SpanExporter
from claimpilot.rag.pipeline import RagPipeline


def build_graph(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    rag: RagPipeline | None = None,
    span_exporter: SpanExporter | None = None,
) -> CompiledStateGraph:  # type: ignore[type-arg]
    """Construct and compile the claim-adjudication graph.

    Parameters
    ----------
    settings : Settings, optional
        Application settings; defaults are used if ``None``.
    llm : LLMClient, optional
        The LLM client injected into agent nodes.  If ``None``, a default
        fake is created from settings.
    rag : RagPipeline, optional
        An **already-ingested** RAG pipeline for policy retrieval.
        If ``None``, a default pipeline is created from providers.
    span_exporter : SpanExporter, optional
        Receives a :class:`~claimpilot.observability.tracer.SpanData` after
        each node completes.  Defaults to :class:`~claimpilot.observability.tracer.NoOpSpanExporter`
        (zero overhead).  Pass an
        :class:`~claimpilot.observability.tracer.InMemorySpanExporter` in tests
        to assert span emission.
    """
    if settings is None:
        settings = Settings()

    if llm is None or rag is None:
        from claimpilot.infra.di import create_providers

        providers = create_providers(settings)
        if llm is None:
            llm = providers.llm
        if rag is None:
            rag = RagPipeline(
                embedder=providers.embedder,
                vector_store=providers.vector_store,
                reranker=providers.reranker,
                settings=settings,
            )

    _exp: SpanExporter = span_exporter if span_exporter is not None else NoOpSpanExporter()

    graph = StateGraph(GraphState)

    # ── Nodes — async agent nodes via _safe, sync routing/terminal via _timed ─
    graph.add_node("intake", _safe("intake", nodes.intake, _exp))
    graph.add_node(
        "policy_retrieval",
        _safe("policy_retrieval", nodes.make_policy_retrieval_node(rag), _exp),
    )
    graph.add_node(
        "coverage_decision",
        _safe("coverage_decision", nodes.make_coverage_node(llm), _exp),
    )

    claims_history_srv = ClaimsHistoryServer()
    fraud_signals_srv = FraudSignalsServer()
    regs_srv = RegsServer()

    graph.add_node(
        "fraud_risk",
        _safe(
            "fraud_risk",
            nodes.make_fraud_risk_node(
                llm,
                claims_history=claims_history_srv,
                fraud_signals=fraud_signals_srv,
            ),
            _exp,
        ),
    )
    graph.add_node("settlement", _safe("settlement", nodes.make_settlement_node(llm), _exp))
    graph.add_node(
        "compliance",
        _safe("compliance", nodes.make_compliance_node(llm, regs=regs_srv), _exp),
    )
    graph.add_node("route", _timed("route", nodes.make_route_node(settings), _exp))
    graph.add_node("finalize_auto", _timed("finalize_auto", nodes.finalize_auto, _exp))
    graph.add_node("human_escalation", _timed("human_escalation", nodes.human_escalation, _exp))
    graph.add_node("error_handler", _timed("error_handler", nodes.error_handler, _exp))

    # ── Linear edges ──────────────────────────────────────────────────────────
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "policy_retrieval")
    graph.add_edge("policy_retrieval", "coverage_decision")
    graph.add_edge("coverage_decision", "fraud_risk")
    graph.add_edge("fraud_risk", "settlement")
    graph.add_edge("settlement", "compliance")
    graph.add_edge("compliance", "route")

    # ── Conditional routing ───────────────────────────────────────────────────
    graph.add_conditional_edges(
        "route",
        _route_decision,
        {
            "finalize_auto": "finalize_auto",
            "human_escalation": "human_escalation",
            "error_handler": "error_handler",
        },
    )

    # ── Terminal edges ────────────────────────────────────────────────────────
    graph.add_edge("finalize_auto", END)
    graph.add_edge("error_handler", "human_escalation")
    graph.add_edge("human_escalation", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _route_decision(state: GraphState) -> str:
    """Conditional edge function after the ``route`` node."""
    if state.get("errors"):
        return "error_handler"
    disposition = state.get("disposition")
    if disposition in ("auto_approved", "auto_denied"):
        return "finalize_auto"
    return "human_escalation"


def _emit(
    exporter: SpanExporter,
    name: str,
    claim_id: str,
    duration_ms: float,
    *,
    start_time: datetime | None = None,
    status_ok: bool = True,
    error_message: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Build and export a :class:`~claimpilot.observability.tracer.SpanData`."""
    now = datetime.now(tz=UTC)
    exporter.export(
        SpanData(
            name=name,
            claim_id=claim_id,
            start_time=start_time or now,
            end_time=now,
            duration_ms=duration_ms,
            attributes=attributes or {},
            status_ok=status_ok,
            error_message=error_message,
        )
    )


def _patch_trace_latency(result: dict[str, Any], latency_ms: float) -> None:
    """In-place: set ``latency_ms`` on the last ``StepTrace`` in ``result['trace']``.

    Called from the ``finally`` block of ``_safe`` / ``_timed`` after the node
    returns.  Because Python's ``return`` passes a reference (not a copy), the
    mutation is visible to the caller even though it runs after ``return``.
    """
    traces: list[StepTrace] = result.get("trace", [])
    if traces:
        patched = list(traces)
        patched[-1] = patched[-1].model_copy(update={"latency_ms": latency_ms})
        result["trace"] = patched


def _safe(name: str, fn: Callable[..., Any], exporter: SpanExporter) -> Callable[..., Any]:
    """Wrap an async (or sync) agent node to:

    - Skip execution if a prior error occurred (preserving existing behaviour).
    - Catch exceptions and convert them to :class:`~claimpilot.models.trace.AgentError`.
    - Measure wall-clock latency and patch ``StepTrace.latency_ms``.
    - Emit a :class:`~claimpilot.observability.tracer.SpanData` via *exporter*.
    """

    @functools.wraps(fn)
    async def wrapper(state: GraphState) -> dict[str, Any]:
        claim_id = str(state.get("claim_id", ""))

        # Short-circuit: skip this node when a prior node recorded an error.
        if state.get("errors"):
            _emit(exporter, name, claim_id, 0.0, attributes={"skipped": True})
            return {"trace": [StepTrace(node=name, outputs={"skipped": "previous error"})]}

        start_time = datetime.now(tz=UTC)
        t0 = time.perf_counter()
        status_ok = True
        error_msg: str | None = None
        result: dict[str, Any] = {}

        try:
            raw = fn(state)
            # Support both sync and async node functions.
            if hasattr(raw, "__await__"):
                raw = await raw
            result = raw
            return result  # noqa: RET504
        except Exception as exc:
            status_ok = False
            error_msg = str(exc)
            error = getattr(exc, "error", None)
            if not isinstance(error, AgentError):
                error = AgentError(
                    node=name,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            trace = StepTrace(node=name, outputs={"error": str(exc)})
            result = {"errors": [error], "trace": [trace]}
            return result  # noqa: RET504
        finally:
            latency_ms = (time.perf_counter() - t0) * 1000
            _patch_trace_latency(result, latency_ms)
            _emit(
                exporter,
                name,
                claim_id,
                latency_ms,
                start_time=start_time,
                status_ok=status_ok,
                error_message=error_msg,
            )

    return wrapper


def _timed(name: str, fn: Callable[..., Any], exporter: SpanExporter) -> Callable[..., Any]:
    """Wrap a *synchronous* routing / terminal node to measure latency and emit a span.

    Unlike ``_safe``, this wrapper does not catch exceptions — routing and
    terminal nodes use simple logic that should never raise in normal operation.
    """

    @functools.wraps(fn)
    def wrapper(state: GraphState) -> dict[str, Any]:
        claim_id = str(state.get("claim_id", ""))
        start_time = datetime.now(tz=UTC)
        t0 = time.perf_counter()
        result: dict[str, Any] = {}
        try:
            result = fn(state)
            return result  # noqa: RET504
        finally:
            latency_ms = (time.perf_counter() - t0) * 1000
            _patch_trace_latency(result, latency_ms)
            _emit(exporter, name, claim_id, latency_ms, start_time=start_time)

    return wrapper
