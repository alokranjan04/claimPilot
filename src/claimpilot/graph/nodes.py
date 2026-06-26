"""Graph node functions — each wraps a specialist agent or routing logic.

Nodes receive ``GraphState``, call the agent, append a ``StepTrace``,
and return a partial state update dict.  The ``LLMClient`` is threaded
through via closures built by ``build_graph``.

Intake remains a stub (real extraction arrives in a later milestone).
Policy-retrieval is wired to the real RAG pipeline.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from claimpilot.agents.compliance import review as compliance_review
from claimpilot.agents.coverage import decide as coverage_decide
from claimpilot.agents.fraud_risk import assess as fraud_assess
from claimpilot.agents.settlement import compute as settlement_compute
from claimpilot.graph.state import GraphState
from claimpilot.infra.interfaces import LLMClient
from claimpilot.infra.settings import Settings
from claimpilot.mcp_servers.claims_history import ClaimsHistoryServer
from claimpilot.mcp_servers.fraud_signals import FraudSignalsServer
from claimpilot.mcp_servers.regs import RegsServer
from claimpilot.models.claim import ClaimFacts
from claimpilot.models.common import Party
from claimpilot.models.decisions import PolicyContext
from claimpilot.models.trace import StepTrace
from claimpilot.rag.pipeline import RagPipeline

# ---------------------------------------------------------------------------
# Stub nodes (intake — real extraction arrives in a later milestone)
# ---------------------------------------------------------------------------


def intake(state: GraphState) -> dict[str, Any]:
    """Stub: extract ClaimFacts from the raw FNOL."""
    raw = state["raw_input"]
    match = re.search(r"\$(\d[\d,]*(?:\.\d{1,2})?)", raw.fnol_text)
    amount = Decimal(match.group(1).replace(",", "")) if match else Decimal("5000")

    facts = ClaimFacts(
        incident_type="auto_collision",
        incident_date=date.today(),
        claimed_amount=amount,
        location="Springfield, IL",
        parties=[Party(name="Stub Claimant", role="claimant")],
    )
    trace = StepTrace(node="intake", inputs={"claim_id": raw.claim_id}, outputs=facts.model_dump())
    return {"facts": facts, "trace": [trace]}


# ---------------------------------------------------------------------------
# Real policy retrieval via RAG pipeline
# ---------------------------------------------------------------------------


def make_policy_retrieval_node(rag: RagPipeline):  # type: ignore[no-untyped-def]
    """Create the policy-retrieval graph node backed by the RAG pipeline."""

    async def policy_retrieval(state: GraphState) -> dict[str, Any]:
        facts = state.get("facts")
        claim_id = state.get("claim_id", "")
        policy_number = state["raw_input"].policy_number

        # Build a retrieval query from the claim facts.
        if facts is not None:
            query = f"{facts.incident_type} coverage claimed amount ${facts.claimed_amount}"
        else:
            query = state["raw_input"].fnol_text

        result = await rag.retrieve(query)

        # Map RetrievalResult → PolicyContext.
        citations = [ch.citation for ch in result.chunks]
        coverage_terms = list({ch.citation.document for ch in result.chunks})
        exclusions: list[str] = []
        for ch in result.chunks:
            lower = ch.text.lower()
            if "exclud" in lower or "exclusion" in lower or "not cover" in lower:
                exclusions.append(ch.citation.clause_id)

        # Ensure at least one citation for PolicyContext validator.
        if not citations:
            from claimpilot.models.common import Citation

            citations = [
                Citation(
                    clause_id="none",
                    document="no-match",
                    snippet="No relevant policy clauses found.",
                )
            ]
            coverage_terms = ["no matching coverage"]

        ctx = PolicyContext(
            policy_id=policy_number,
            coverage_terms=coverage_terms or ["unknown"],
            exclusions=exclusions,
            citations=citations,
            sufficient=result.sufficient,
        )
        trace = StepTrace(
            node="policy_retrieval",
            inputs={"claim_id": claim_id, "query": query},
            outputs={
                "policy_id": ctx.policy_id,
                "sufficient": ctx.sufficient,
                "chunks_returned": len(result.chunks),
            },
        )
        return {"policy_context": ctx, "trace": [trace]}

    return policy_retrieval


# ---------------------------------------------------------------------------
# Real agent nodes (closures built via make_*_node)
# ---------------------------------------------------------------------------


def make_coverage_node(llm: LLMClient):  # type: ignore[no-untyped-def]
    """Create the coverage-decision graph node."""

    async def coverage_decision(state: GraphState) -> dict[str, Any]:
        facts = state["facts"]
        ctx = state["policy_context"]
        assert facts is not None and ctx is not None
        opinion = await coverage_decide(facts, ctx, llm=llm)
        trace = StepTrace(
            node="coverage_decision",
            inputs={"claim_id": state.get("claim_id", "")},
            outputs=opinion.model_dump(),
            citations=list(opinion.citations),
        )
        return {"coverage": opinion, "trace": [trace]}

    return coverage_decision


def make_fraud_risk_node(  # type: ignore[no-untyped-def]
    llm: LLMClient,
    *,
    claims_history: ClaimsHistoryServer | None = None,
    fraud_signals: FraudSignalsServer | None = None,
):
    """Create the fraud/risk-scoring graph node."""

    async def fraud_risk(state: GraphState) -> dict[str, Any]:
        facts = state["facts"]
        assert facts is not None
        assessment = await fraud_assess(
            facts,
            llm=llm,
            claims_history=claims_history,
            fraud_signals=fraud_signals,
        )
        tool_calls: list[str] = []
        if claims_history is not None:
            tool_calls.append("claims_history.lookup")
        if fraud_signals is not None:
            tool_calls.append("fraud_signals.score")
        trace = StepTrace(
            node="fraud_risk",
            inputs={"claim_id": state.get("claim_id", ""), "tool_calls": tool_calls},
            outputs=assessment.model_dump(),
        )
        return {"risk": assessment, "trace": [trace]}

    return fraud_risk


def make_settlement_node(llm: LLMClient):  # type: ignore[no-untyped-def]
    """Create the settlement-computation graph node."""

    async def settlement(state: GraphState) -> dict[str, Any]:
        facts = state["facts"]
        coverage = state["coverage"]
        assert facts is not None and coverage is not None
        proposal = await settlement_compute(facts, coverage, llm=llm)
        trace = StepTrace(
            node="settlement",
            inputs={"claim_id": state.get("claim_id", "")},
            outputs=proposal.model_dump(),
        )
        return {"settlement": proposal, "trace": [trace]}

    return settlement


def make_compliance_node(  # type: ignore[no-untyped-def]
    llm: LLMClient,
    *,
    regs: RegsServer | None = None,
):
    """Create the compliance/audit graph node."""

    async def compliance(state: GraphState) -> dict[str, Any]:
        facts = state["facts"]
        ctx = state["policy_context"]
        coverage = state["coverage"]
        settle = state["settlement"]
        assert facts is not None and ctx is not None
        assert coverage is not None and settle is not None
        verdict = await compliance_review(facts, ctx, coverage, settle, llm=llm, regs=regs)
        tool_calls: list[str] = []
        if regs is not None:
            tool_calls.append("regs.search")
        trace = StepTrace(
            node="compliance",
            inputs={"claim_id": state.get("claim_id", ""), "tool_calls": tool_calls},
            outputs=verdict.model_dump(),
        )
        return {"compliance": verdict, "trace": [trace]}

    return compliance


# ---------------------------------------------------------------------------
# Routing + terminal nodes
# ---------------------------------------------------------------------------


def make_route_node(settings: Settings):  # type: ignore[no-untyped-def]
    """Create the routing decision node (supervisor logic)."""

    def route(state: GraphState) -> dict[str, Any]:
        errors = state.get("errors", [])
        coverage = state.get("coverage")
        risk = state.get("risk")
        settle = state.get("settlement")
        comp = state.get("compliance")

        if errors:
            disposition = "escalated"
        elif (
            coverage
            and risk
            and settle
            and comp
            and coverage.confidence >= settings.threshold_coverage_confidence
            and risk.score <= settings.threshold_risk_score
            and settle.payable_amount <= settings.threshold_max_auto_amount
            and comp.passed
        ):
            disposition = "auto_denied" if coverage.decision == "denied" else "auto_approved"
        else:
            disposition = "escalated"

        trace = StepTrace(
            node="route",
            inputs={
                "coverage_confidence": coverage.confidence if coverage else None,
                "risk_score": risk.score if risk else None,
                "payable": str(settle.payable_amount) if settle else None,
                "compliance_passed": comp.passed if comp else None,
                "error_count": len(errors),
            },
            outputs={"disposition": disposition},
        )
        return {"disposition": disposition, "trace": [trace]}

    return route


def finalize_auto(state: GraphState) -> dict[str, Any]:
    """Terminal node for auto-approved/denied claims."""
    trace = StepTrace(
        node="finalize_auto",
        inputs={"disposition": state.get("disposition")},
        outputs={"finalized": True},
    )
    return {"trace": [trace]}


def human_escalation(state: GraphState) -> dict[str, Any]:
    """Terminal node for escalated claims."""
    trace = StepTrace(
        node="human_escalation",
        inputs={"disposition": state.get("disposition")},
        outputs={"escalated": True},
    )
    return {"disposition": "escalated", "trace": [trace]}


def error_handler(state: GraphState) -> dict[str, Any]:
    """Process errors and route to human escalation."""
    errors = state.get("errors", [])
    trace = StepTrace(
        node="error_handler",
        inputs={"error_count": len(errors)},
        outputs={"errors_processed": len(errors)},
    )
    return {"disposition": "escalated", "trace": [trace]}
