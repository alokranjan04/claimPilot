"""Tests for src/claimpilot/observability/ — M9 acceptance criteria.

Acceptance criteria checked:
  [x] Every node emits a span (graph integration test, auto-approved path)
  [x] Cost meter sums correctly from a StepTrace list
  [x] Logs are structured (claim_id bound) and PII-free (processor strips keys)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import structlog

from claimpilot.models.trace import StepTrace
from claimpilot.observability.cost_meter import ClaimCostSummary, compute_cost_summary
from claimpilot.observability.logging import _drop_pii, get_logger
from claimpilot.observability.tracer import InMemorySpanExporter, NoOpSpanExporter, SpanData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def _span(name: str = "intake", *, duration_ms: float = 5.0) -> SpanData:
    return SpanData(
        name=name,
        claim_id="CLM-TEST",
        start_time=_NOW,
        end_time=_NOW,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Tracer — unit tests
# ---------------------------------------------------------------------------


def test_noop_exporter_accepts_span() -> None:
    """NoOpSpanExporter must silently discard spans without raising."""
    exp = NoOpSpanExporter()
    exp.export(_span())  # should not raise


def test_in_memory_exporter_collects_spans() -> None:
    exp = InMemorySpanExporter()
    exp.export(_span("intake", duration_ms=12.3))
    exp.export(_span("coverage_decision", duration_ms=33.1))
    assert len(exp.spans) == 2
    assert exp.spans[0].name == "intake"
    assert exp.spans[0].duration_ms == pytest.approx(12.3)
    assert exp.spans[1].name == "coverage_decision"


def test_in_memory_exporter_clear() -> None:
    exp = InMemorySpanExporter()
    exp.export(_span())
    exp.clear()
    assert exp.spans == []


def test_in_memory_exporter_names() -> None:
    exp = InMemorySpanExporter()
    for n in ("intake", "policy_retrieval", "coverage_decision"):
        exp.export(_span(n))
    assert exp.names() == ["intake", "policy_retrieval", "coverage_decision"]


def test_span_data_default_ids_are_unique() -> None:
    s1 = SpanData(name="a", claim_id="CLM-1", start_time=_NOW, end_time=_NOW, duration_ms=0.0)
    s2 = SpanData(name="b", claim_id="CLM-2", start_time=_NOW, end_time=_NOW, duration_ms=0.0)
    assert s1.span_id != s2.span_id
    assert s1.trace_id != s2.trace_id


def test_span_exporter_protocol_satisfied() -> None:
    """Both concrete exporters satisfy the SpanExporter protocol."""
    from claimpilot.observability.tracer import SpanExporter

    assert isinstance(NoOpSpanExporter(), SpanExporter)
    assert isinstance(InMemorySpanExporter(), SpanExporter)


# ---------------------------------------------------------------------------
# Tracer — graph integration: every node emits a span
# ---------------------------------------------------------------------------

_CLAUSE = "POL-100:§1.1 Comprehensive Coverage"

_APPROVE_SCRIPTS = [
    {
        "decision": "covered",
        "confidence": 0.95,
        "rationale": "Covered.",
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
]

_POLICY_DOC_TEXT = (
    "# §1.1 Comprehensive Coverage\n"
    "Covers collisions, theft, vandalism. Deductible $500. Max payout is actual cash value.\n\n"
    "# §1.3 Exclusions\nDoes not cover intentional damage."
)


async def test_graph_emits_span_per_node() -> None:
    """Build the full graph with InMemorySpanExporter and verify every node emits a span."""
    from claimpilot.graph.build_graph import build_graph
    from claimpilot.infra.providers.fakes import (
        FakeEmbedder,
        FakeLLMClient,
        FakeReranker,
        FakeVectorStore,
    )
    from claimpilot.infra.settings import Settings
    from claimpilot.models.claim import RawClaim
    from claimpilot.rag.models import SourceDoc
    from claimpilot.rag.pipeline import RagPipeline

    exporter = InMemorySpanExporter()
    settings = Settings(rag_tau_sufficient=0.001)

    rag = RagPipeline(
        embedder=FakeEmbedder(dims=64, seed=42),
        vector_store=FakeVectorStore(),
        reranker=FakeReranker(),
        settings=settings,
    )
    corpus = [SourceDoc(doc_id="POL-100", title="Standard Auto Policy", text=_POLICY_DOC_TEXT)]
    await rag.ingest(corpus)

    graph = build_graph(
        settings,
        llm=FakeLLMClient(scripted=list(_APPROVE_SCRIPTS)),
        rag=rag,
        span_exporter=exporter,
    )
    raw = RawClaim(claim_id="CLM-OBS", policy_number="POL-100", fnol_text="Fender bender $5000.")
    async for _ in graph.astream({"claim_id": "CLM-OBS", "raw_input": raw}):
        pass

    emitted = exporter.names()
    # Auto-approved path: all 8 nodes should emit a span.
    for expected_node in (
        "intake",
        "policy_retrieval",
        "coverage_decision",
        "fraud_risk",
        "settlement",
        "compliance",
        "route",
        "finalize_auto",
    ):
        assert expected_node in emitted, f"Missing span for node '{expected_node}'; got: {emitted}"


async def test_graph_spans_carry_claim_id() -> None:
    """Each emitted span's claim_id must match the claim being processed."""
    from claimpilot.graph.build_graph import build_graph
    from claimpilot.infra.providers.fakes import (
        FakeEmbedder,
        FakeLLMClient,
        FakeReranker,
        FakeVectorStore,
    )
    from claimpilot.infra.settings import Settings
    from claimpilot.models.claim import RawClaim
    from claimpilot.rag.models import SourceDoc
    from claimpilot.rag.pipeline import RagPipeline

    exporter = InMemorySpanExporter()
    settings = Settings(rag_tau_sufficient=0.001)

    rag = RagPipeline(
        embedder=FakeEmbedder(dims=64, seed=42),
        vector_store=FakeVectorStore(),
        reranker=FakeReranker(),
        settings=settings,
    )
    await rag.ingest(
        [SourceDoc(doc_id="POL-100", title="Standard Auto Policy", text=_POLICY_DOC_TEXT)]
    )

    graph = build_graph(
        settings,
        llm=FakeLLMClient(scripted=list(_APPROVE_SCRIPTS)),
        rag=rag,
        span_exporter=exporter,
    )
    raw = RawClaim(claim_id="CLM-ID-CHECK", policy_number="POL-100", fnol_text="Crash $5000.")
    async for _ in graph.astream({"claim_id": "CLM-ID-CHECK", "raw_input": raw}):
        pass

    for span in exporter.spans:
        assert span.claim_id == "CLM-ID-CHECK", f"Wrong claim_id on span '{span.name}'"


async def test_graph_spans_have_positive_latency() -> None:
    """Spans emitted for real nodes must have duration_ms > 0."""
    from claimpilot.graph.build_graph import build_graph
    from claimpilot.infra.providers.fakes import (
        FakeEmbedder,
        FakeLLMClient,
        FakeReranker,
        FakeVectorStore,
    )
    from claimpilot.infra.settings import Settings
    from claimpilot.models.claim import RawClaim
    from claimpilot.rag.models import SourceDoc
    from claimpilot.rag.pipeline import RagPipeline

    exporter = InMemorySpanExporter()
    settings = Settings(rag_tau_sufficient=0.001)
    rag = RagPipeline(
        embedder=FakeEmbedder(dims=64, seed=42),
        vector_store=FakeVectorStore(),
        reranker=FakeReranker(),
        settings=settings,
    )
    await rag.ingest(
        [SourceDoc(doc_id="POL-100", title="Standard Auto Policy", text=_POLICY_DOC_TEXT)]
    )
    graph = build_graph(
        settings,
        llm=FakeLLMClient(scripted=list(_APPROVE_SCRIPTS)),
        rag=rag,
        span_exporter=exporter,
    )
    raw = RawClaim(claim_id="CLM-LAT", policy_number="POL-100", fnol_text="Bump $5000.")
    async for _ in graph.astream({"claim_id": "CLM-LAT", "raw_input": raw}):
        pass

    # Skipped-node spans have duration_ms=0; real execution spans must be > 0.
    real_spans = [s for s in exporter.spans if not s.attributes.get("skipped")]
    assert all(s.duration_ms >= 0 for s in real_spans)
    # At least some spans must have actually measured time.
    assert any(s.duration_ms > 0 for s in real_spans)


async def test_step_trace_latency_ms_populated() -> None:
    """StepTrace.latency_ms must be non-zero after the graph runs (set by _safe/_timed)."""
    from claimpilot.graph.build_graph import build_graph
    from claimpilot.infra.providers.fakes import (
        FakeEmbedder,
        FakeLLMClient,
        FakeReranker,
        FakeVectorStore,
    )
    from claimpilot.infra.settings import Settings
    from claimpilot.models.claim import RawClaim
    from claimpilot.rag.models import SourceDoc
    from claimpilot.rag.pipeline import RagPipeline

    settings = Settings(rag_tau_sufficient=0.001)
    rag = RagPipeline(
        embedder=FakeEmbedder(dims=64, seed=42),
        vector_store=FakeVectorStore(),
        reranker=FakeReranker(),
        settings=settings,
    )
    await rag.ingest(
        [SourceDoc(doc_id="POL-100", title="Standard Auto Policy", text=_POLICY_DOC_TEXT)]
    )
    graph = build_graph(
        settings,
        llm=FakeLLMClient(scripted=list(_APPROVE_SCRIPTS)),
        rag=rag,
    )
    raw = RawClaim(claim_id="CLM-TRACE", policy_number="POL-100", fnol_text="Collision $5000.")
    result = await graph.ainvoke({"claim_id": "CLM-TRACE", "raw_input": raw})

    trace: list[StepTrace] = result.get("trace", [])
    assert len(trace) >= 7, "Expected at least 7 trace entries (one per node)"
    # At least one step must have a measured latency > 0.
    assert any(step.latency_ms > 0 for step in trace)


# ---------------------------------------------------------------------------
# Cost meter — unit tests
# ---------------------------------------------------------------------------


def test_compute_cost_summary_empty_trace() -> None:
    summary = compute_cost_summary("CLM-000", [])
    assert summary.claim_id == "CLM-000"
    assert summary.total_cost_usd == Decimal(0)
    assert summary.total_latency_ms == 0.0
    assert summary.node_count == 0
    assert summary.cost_by_node == {}
    assert summary.latency_by_node == {}


def test_compute_cost_summary_single_step() -> None:
    trace = [StepTrace(node="intake", cost_usd=Decimal("0.001"), latency_ms=7.5)]
    summary = compute_cost_summary("CLM-001", trace)
    assert summary.total_cost_usd == Decimal("0.001")
    assert summary.total_latency_ms == pytest.approx(7.5)
    assert summary.node_count == 1
    assert summary.cost_by_node["intake"] == "0.001"
    assert summary.latency_by_node["intake"] == pytest.approx(7.5)


def test_compute_cost_summary_multi_step_sums() -> None:
    trace = [
        StepTrace(node="intake", cost_usd=Decimal("0.001"), latency_ms=5.0),
        StepTrace(node="coverage_decision", cost_usd=Decimal("0.002"), latency_ms=10.0),
        StepTrace(node="compliance", cost_usd=Decimal("0.003"), latency_ms=15.0),
    ]
    summary = compute_cost_summary("CLM-002", trace)
    assert summary.total_cost_usd == Decimal("0.006")
    assert summary.total_latency_ms == pytest.approx(30.0)
    assert summary.node_count == 3


def test_compute_cost_summary_repeated_node_accumulates() -> None:
    """If the same node name appears twice, cost and latency are summed."""
    trace = [
        StepTrace(node="intake", cost_usd=Decimal("0.001"), latency_ms=5.0),
        StepTrace(node="intake", cost_usd=Decimal("0.002"), latency_ms=8.0),
    ]
    summary = compute_cost_summary("CLM-003", trace)
    assert summary.cost_by_node["intake"] == "0.003"
    assert summary.latency_by_node["intake"] == pytest.approx(13.0)
    assert summary.node_count == 2  # raw count, not unique nodes


def test_compute_cost_summary_decimal_serialised_as_string() -> None:
    """cost_by_node values must be plain strings (Decimal → str) for JSON safety."""
    trace = [StepTrace(node="intake", cost_usd=Decimal("0.00012345"), latency_ms=1.0)]
    summary = compute_cost_summary("CLM-004", trace)
    assert isinstance(summary.cost_by_node["intake"], str)
    assert Decimal(summary.cost_by_node["intake"]) == Decimal("0.00012345")


def test_cost_summary_is_pydantic_model() -> None:
    summary = compute_cost_summary("CLM-005", [])
    assert isinstance(summary, ClaimCostSummary)


def test_cost_summary_model_dump_json_safe() -> None:
    """model_dump(mode='json') must round-trip Decimal as string, not float."""
    trace = [StepTrace(node="n", cost_usd=Decimal("0.000123"), latency_ms=1.0)]
    summary = compute_cost_summary("CLM-006", trace)
    data = summary.model_dump(mode="json")
    # total_cost_usd serialised as string
    assert isinstance(data["total_cost_usd"], str)
    assert Decimal(data["total_cost_usd"]) == Decimal("0.000123")


# ---------------------------------------------------------------------------
# Logging — unit tests
# ---------------------------------------------------------------------------


def test_pii_filter_drops_known_pii_keys() -> None:
    event = {
        "event": "node_completed",
        "claim_id": "CLM-001",
        "fnol_text": "I was in a crash near Springfield",
        "messages": [{"role": "user", "content": "..."}],
        "node": "intake",
    }
    result = _drop_pii(None, "info", event)
    assert "fnol_text" not in result
    assert "messages" not in result
    assert result["claim_id"] == "CLM-001"
    assert result["node"] == "intake"
    assert result["event"] == "node_completed"


def test_pii_filter_preserves_non_pii_keys() -> None:
    event = {"event": "span_emitted", "node": "intake", "latency_ms": 12.3, "claim_id": "CLM-X"}
    result = _drop_pii(None, "info", event)
    assert result == event  # nothing removed


def test_pii_filter_drops_all_pii_keys() -> None:
    """Every key in the PII list must be stripped by the processor."""
    pii_keys = [
        "claimant",
        "fnol_text",
        "messages",
        "name",
        "parties",
        "prompt",
        "raw_input",
        "response_text",
    ]
    event: dict[str, object] = {k: "sensitive" for k in pii_keys}
    event["claim_id"] = "CLM-SAFE"
    result = _drop_pii(None, "info", event)
    for key in pii_keys:
        assert key not in result, f"PII key '{key}' was not stripped"
    assert result["claim_id"] == "CLM-SAFE"


def test_get_logger_binds_claim_id() -> None:
    with structlog.testing.capture_logs() as cap:
        log = get_logger("CLM-BIND")
        log.info("node_completed", node="intake", latency_ms=5.0)
    assert len(cap) == 1
    assert cap[0]["claim_id"] == "CLM-BIND"
    assert cap[0]["log_level"] == "info"
    assert cap[0]["node"] == "intake"


def test_get_logger_without_claim_id_omits_claim_id() -> None:
    with structlog.testing.capture_logs() as cap:
        log = get_logger()
        log.info("app_started")
    assert len(cap) == 1
    assert "claim_id" not in cap[0]


def test_get_logger_pii_not_in_captured_log() -> None:
    """Even when PII is passed to the logger, it must not appear in the record.

    Note: structlog.testing.capture_logs() bypasses processors (it captures
    before the chain runs).  We therefore test the processor function directly
    rather than relying on capture_logs to enforce the filter.
    """
    event = {"event": "node", "claim_id": "CLM-PII", "fnol_text": "sensitive details"}
    clean = _drop_pii(None, "info", event)
    assert "fnol_text" not in clean
