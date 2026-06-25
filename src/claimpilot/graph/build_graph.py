"""Build the LangGraph state machine for claim adjudication.

Topology per master-spec §5::

    START → intake → policy_retrieval → coverage_decision → fraud_risk
          → settlement → compliance → route
    route ──(auto)──▶ finalize_auto → END
    route ──(escalate)──▶ human_escalation → END
    route ──(errors)──▶ error_handler → human_escalation → END
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from claimpilot.graph import nodes
from claimpilot.graph.state import GraphState
from claimpilot.infra.interfaces import LLMClient
from claimpilot.infra.settings import Settings
from claimpilot.models.trace import AgentError, StepTrace
from claimpilot.rag.pipeline import RagPipeline


def build_graph(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    rag: RagPipeline | None = None,
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

    graph = StateGraph(GraphState)

    # ── Nodes ─────────────────────────────────────────────────────────
    graph.add_node("intake", _safe("intake", nodes.intake))
    graph.add_node(
        "policy_retrieval",
        _safe("policy_retrieval", nodes.make_policy_retrieval_node(rag)),
    )
    graph.add_node("coverage_decision", _safe("coverage_decision", nodes.make_coverage_node(llm)))
    graph.add_node("fraud_risk", _safe("fraud_risk", nodes.make_fraud_risk_node(llm)))
    graph.add_node("settlement", _safe("settlement", nodes.make_settlement_node(llm)))
    graph.add_node("compliance", _safe("compliance", nodes.make_compliance_node(llm)))
    graph.add_node("route", nodes.make_route_node(settings))
    graph.add_node("finalize_auto", nodes.finalize_auto)
    graph.add_node("human_escalation", nodes.human_escalation)
    graph.add_node("error_handler", nodes.error_handler)

    # ── Linear edges ──────────────────────────────────────────────────
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "policy_retrieval")
    graph.add_edge("policy_retrieval", "coverage_decision")
    graph.add_edge("coverage_decision", "fraud_risk")
    graph.add_edge("fraud_risk", "settlement")
    graph.add_edge("settlement", "compliance")
    graph.add_edge("compliance", "route")

    # ── Conditional routing ───────────────────────────────────────────
    graph.add_conditional_edges(
        "route",
        _route_decision,
        {
            "finalize_auto": "finalize_auto",
            "human_escalation": "human_escalation",
            "error_handler": "error_handler",
        },
    )

    # ── Terminal edges ────────────────────────────────────────────────
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


def _safe(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a node function to catch agent errors and record them."""

    @functools.wraps(fn)
    async def wrapper(state: GraphState) -> dict[str, Any]:
        if state.get("errors"):
            return {"trace": [StepTrace(node=name, outputs={"skipped": "previous error"})]}
        try:
            result = fn(state)
            # Handle both sync and async node functions.
            if hasattr(result, "__await__"):
                result = await result
            return result  # type: ignore[no-any-return]
        except Exception as exc:
            # Extract AgentError if available.
            error = getattr(exc, "error", None)
            if not isinstance(error, AgentError):
                error = AgentError(
                    node=name,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            trace = StepTrace(node=name, outputs={"error": str(exc)})
            return {"errors": [error], "trace": [trace]}

    return wrapper
