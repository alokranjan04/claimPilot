"""End-to-end integration tests — real agents + real RAG over fakes.

Runs a full claim through the graph from START to END for the
auto-approve, escalate, and insufficient-context paths, asserting
correct dispositions and that every node appends a trace entry.
"""

from __future__ import annotations

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

# Node execution order for the two terminal paths.
_APPROVE_NODES = [
    "intake",
    "policy_retrieval",
    "coverage_decision",
    "fraud_risk",
    "settlement",
    "compliance",
    "route",
    "finalize_auto",
]
_ESCALATE_NODES = [
    "intake",
    "policy_retrieval",
    "coverage_decision",
    "fraud_risk",
    "settlement",
    "compliance",
    "route",
    "human_escalation",
]

# -- Corpus used for all e2e tests ----------------------------------------

_CORPUS = [
    SourceDoc(
        doc_id="POL-100",
        title="Standard Auto Policy",
        text=(
            "# §1.1 Comprehensive Coverage\n"
            "This section covers damage to the insured vehicle from collisions, "
            "theft, vandalism, weather events, and animal strikes. The deductible "
            "is $500 per incident. Maximum payout is the actual cash value.\n\n"
            "# §1.2 Liability Coverage\n"
            "Covers bodily injury and property damage the insured causes to others.\n\n"
            "# §1.3 Exclusions\n"
            "Does not cover intentional damage, racing, or commercial use."
        ),
        metadata={"jurisdiction": "IL", "policy_type": "auto"},
    ),
]


def _test_settings(**overrides: object) -> Settings:
    """Settings with a low tau so fake-embedder scores count as sufficient."""
    defaults: dict[str, object] = {"rag_tau_sufficient": 0.001}
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


async def _make_rag(settings: Settings | None = None) -> RagPipeline:
    """Create and ingest a RAG pipeline with the test corpus."""
    s = settings or _test_settings()
    rag = RagPipeline(
        embedder=FakeEmbedder(dims=64, seed=42),
        vector_store=FakeVectorStore(),
        reranker=FakeReranker(),
        settings=s,
    )
    await rag.ingest(_CORPUS)
    return rag


# -- Scripted LLM factories -----------------------------------------------
# Citation clause_ids must match what the RAG pipeline actually returns.
# The chunker produces IDs like "POL-100:§1.1 Comprehensive Coverage".

_CLAUSE_COMP = "POL-100:§1.1 Comprehensive Coverage"
_CLAUSE_LIAB = "POL-100:§1.2 Liability Coverage"


def _auto_approve_llm() -> FakeLLMClient:
    """Fake LLM scripted for the happy auto-approve path."""
    return FakeLLMClient(
        scripted=[
            # 1. Coverage — covered
            {
                "decision": "covered",
                "confidence": 0.95,
                "rationale": "Collision covered under comprehensive coverage.",
                "citations": [
                    {
                        "clause_id": _CLAUSE_COMP,
                        "document": "Standard Auto Policy",
                        "snippet": "covers damage from collisions",
                    },
                ],
            },
            # 2. Fraud — low
            {"score": 0.05, "signals": [], "recommendation": "approve"},
            # 3. Settlement — under threshold
            {
                "payable_amount": "4500.00",
                "deductible_applied": "500.00",
                "limit_applied": "100000.00",
                "breakdown": [{"description": "Repair costs", "amount": "4500.00"}],
            },
            # 4. Compliance — passed
            {
                "passed": True,
                "violations": [],
                "rationale": "All requirements met.",
                "citations": [],
            },
        ]
    )


def _escalate_high_amount_llm() -> FakeLLMClient:
    """Fake LLM scripted for the escalation path (high settlement)."""
    return FakeLLMClient(
        scripted=[
            # 1. Coverage — covered
            {
                "decision": "covered",
                "confidence": 0.95,
                "rationale": "Covered under comprehensive.",
                "citations": [
                    {
                        "clause_id": _CLAUSE_COMP,
                        "document": "Standard Auto Policy",
                        "snippet": "covers damage from collisions",
                    },
                ],
            },
            # 2. Fraud — low
            {"score": 0.05, "signals": [], "recommendation": "approve"},
            # 3. Settlement — ABOVE threshold
            {
                "payable_amount": "49500.00",
                "deductible_applied": "500.00",
                "limit_applied": "100000.00",
                "breakdown": [{"description": "Major repair", "amount": "49500.00"}],
            },
            # 4. Compliance — passed
            {
                "passed": True,
                "violations": [],
                "rationale": "All requirements met.",
                "citations": [],
            },
        ]
    )


# -- Tests -----------------------------------------------------------------


class TestAutoApprovePath:
    async def test_auto_approve_e2e(self) -> None:
        """Low-amount, clean claim → auto_approved with trace at every node."""
        settings = _test_settings()
        rag = await _make_rag(settings)
        graph = build_graph(settings, llm=_auto_approve_llm(), rag=rag)

        raw = RawClaim(
            claim_id="CLM-001",
            policy_number="POL-100",
            fnol_text="Minor fender bender. Estimated damage $5000.",
        )

        result = await graph.ainvoke({"claim_id": raw.claim_id, "raw_input": raw})

        assert result["disposition"] == "auto_approved"
        trace_nodes = [t.node for t in result["trace"]]
        assert trace_nodes == _APPROVE_NODES

        assert result["facts"] is not None
        assert result["policy_context"] is not None
        assert result["policy_context"].sufficient is True
        assert result["coverage"] is not None
        assert result["coverage"].decision == "covered"
        assert result["risk"] is not None
        assert result["risk"].score <= 0.3
        assert result["settlement"] is not None
        assert result["compliance"] is not None
        assert result["compliance"].passed is True
        assert not result.get("errors")

    async def test_mcp_tool_calls_in_trace(self) -> None:
        """MCP tool calls are recorded in fraud_risk and compliance traces."""
        settings = _test_settings()
        rag = await _make_rag(settings)
        graph = build_graph(settings, llm=_auto_approve_llm(), rag=rag)

        raw = RawClaim(
            claim_id="CLM-MCP",
            policy_number="POL-100",
            fnol_text="Fender bender. Damage $5000.",
        )

        result = await graph.ainvoke({"claim_id": raw.claim_id, "raw_input": raw})

        trace_by_node = {t.node: t for t in result["trace"]}

        # fraud_risk node should record claims_history + fraud_signals tool calls.
        fr_trace = trace_by_node["fraud_risk"]
        assert "tool_calls" in fr_trace.inputs
        assert "claims_history.lookup" in fr_trace.inputs["tool_calls"]
        assert "fraud_signals.score" in fr_trace.inputs["tool_calls"]

        # compliance node should record regs.search tool call.
        comp_trace = trace_by_node["compliance"]
        assert "tool_calls" in comp_trace.inputs
        assert "regs.search" in comp_trace.inputs["tool_calls"]


class TestEscalatePath:
    async def test_escalate_high_amount(self) -> None:
        """High-amount claim → escalated with trace at every node."""
        settings = _test_settings()
        rag = await _make_rag(settings)
        graph = build_graph(settings, llm=_escalate_high_amount_llm(), rag=rag)

        raw = RawClaim(
            claim_id="CLM-002",
            policy_number="POL-200",
            fnol_text="Major collision. Estimated damage $50000.",
        )

        result = await graph.ainvoke({"claim_id": raw.claim_id, "raw_input": raw})

        assert result["disposition"] == "escalated"
        trace_nodes = [t.node for t in result["trace"]]
        assert trace_nodes == _ESCALATE_NODES
        assert result["settlement"] is not None
        assert result["settlement"].payable_amount > settings.threshold_max_auto_amount


class TestInsufficientContextPath:
    async def test_insufficient_context_escalates(self) -> None:
        """A claim about a topic not in the corpus → insufficient context
        → coverage agent returns low confidence → escalated."""
        # High tau so fake-embedder scores are always below threshold.
        settings = _test_settings(rag_tau_sufficient=0.99)
        rag = await _make_rag(settings)

        # The coverage agent gets context.sufficient=False and returns
        # low-confidence partial WITHOUT calling the LLM.  The remaining
        # agents still run, but the route escalates on low confidence.
        llm = FakeLLMClient(
            scripted=[
                # Coverage is skipped (insufficient context guard).
                # 1. Fraud — low
                {"score": 0.05, "signals": [], "recommendation": "approve"},
                # 2. Settlement — partial coverage → small amount
                {
                    "payable_amount": "0",
                    "deductible_applied": "0",
                    "limit_applied": "100000",
                    "breakdown": [{"description": "Pending review", "amount": "0"}],
                },
                # 3. Compliance — passed
                {
                    "passed": True,
                    "violations": [],
                    "rationale": "Compliant.",
                    "citations": [],
                },
            ]
        )
        graph = build_graph(settings, llm=llm, rag=rag)

        # Query about something NOT in the auto policy corpus at all.
        raw = RawClaim(
            claim_id="CLM-003",
            policy_number="POL-100",
            fnol_text="Earthquake damaged my quantum computer. $999999.",
        )

        result = await graph.ainvoke({"claim_id": raw.claim_id, "raw_input": raw})

        # Coverage should be partial with low confidence → escalated.
        assert result["coverage"] is not None
        assert result["coverage"].decision == "partial"
        assert result["coverage"].confidence <= 0.2
        assert result["disposition"] == "escalated"
        trace_nodes = [t.node for t in result["trace"]]
        assert trace_nodes == _ESCALATE_NODES
