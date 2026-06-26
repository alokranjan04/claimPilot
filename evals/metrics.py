"""Evaluation metrics and scorecard for ClaimPilot.

Spec: master-spec §11 — "Eval harness is the differentiator."

Shapes:
  GoldenDataset → loaded from evals/golden/cases.json
  EvalCase      → one test case (claim + scripted LLM + expected outcome)
  CaseResult    → outcome of running one case through the graph
  Scorecard     → aggregated metrics + CI gate pass/fail
"""

from __future__ import annotations

import statistics
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# M9 cost model — mirrors observability/cost_meter.py (GPT-4o tier, mid-2025)
# ---------------------------------------------------------------------------

_COST_PER_PROMPT: Decimal = Decimal("0.000005")  # $5 / 1M input tokens
_COST_PER_COMPLETION: Decimal = Decimal("0.000015")  # $15 / 1M output tokens


# ---------------------------------------------------------------------------
# CI gate thresholds — edit here to relax / tighten the gate.
# ---------------------------------------------------------------------------

GATE_DECISION_ACCURACY: float = 0.90
GATE_CITATION_FAITHFULNESS: float = 0.90
GATE_TOOL_CALL_ACCURACY: float = 1.00
GATE_ESCALATION_PRECISION: float = 0.80
GATE_ESCALATION_RECALL: float = 0.80

# ---------------------------------------------------------------------------
# Golden-case input shapes
# ---------------------------------------------------------------------------


class EvalExpected(BaseModel):
    """Expected outcomes for one golden eval case."""

    disposition: str
    """Expected final disposition: 'auto_approved' | 'auto_denied' | 'escalated'."""

    coverage_decision: str | None = None
    """Expected coverage decision ('covered' | 'denied' | 'partial') if checked."""

    expects_tool_calls: list[str] = Field(default_factory=list)
    """Tool names that must appear in the graph trace (MCP tool-call correctness)."""


class EvalCase(BaseModel):
    """One entry in the golden dataset."""

    id: str
    description: str
    tags: list[str] = Field(default_factory=list)

    claim: dict[str, Any]
    """Dict matching ``RawClaim`` fields (claim_id, policy_number, fnol_text)."""

    rag_tau_sufficient: float = 0.001
    """RAG sufficiency threshold for this case (low → sufficient, high → insufficient)."""

    llm_scripted: list[dict[str, Any]]
    """Scripted LLM responses consumed FIFO by the FakeLLMClient.

    Response order matches agent call order:
    - Sufficient context, non-denied coverage:   [coverage, fraud, settlement, compliance]
    - Denied coverage (settlement short-circuits): [coverage, fraud, compliance]
    - Insufficient context (coverage short-circuits): [fraud, settlement, compliance]
    """

    expected: EvalExpected


class GoldenDataset(BaseModel):
    """Full golden dataset: shared corpus + list of cases."""

    corpus: list[dict[str, Any]]
    """Source documents ingested into the RAG pipeline for every case."""

    cases: list[EvalCase]


# ---------------------------------------------------------------------------
# Per-case result
# ---------------------------------------------------------------------------


class CaseResult(BaseModel):
    """Outcome of running one golden case through the graph."""

    case_id: str
    passed: bool

    expected_disposition: str
    actual_disposition: str | None

    disposition_correct: bool
    coverage_decision: str | None = None
    coverage_correct: bool | None = None

    citations_faithful: bool
    """True if every citation clause_id in the coverage opinion came from retrieved context."""

    tool_calls_correct: bool
    """True if all expected MCP tool calls appear in the graph trace."""

    latency_ms: float
    prompt_tokens: int
    completion_tokens: int

    failures: list[str] = Field(default_factory=list)
    """Human-readable reasons this case failed (empty on pass)."""


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------


class Scorecard(BaseModel):
    """Aggregated eval metrics and CI gate result."""

    total_cases: int
    passed: int
    failed: int

    # Accuracy metrics
    decision_accuracy: float
    """Fraction of cases where the actual disposition matches expected."""

    escalation_precision: float
    """Of cases the graph escalated, fraction that truly needed escalation."""

    escalation_recall: float
    """Of cases that needed escalation, fraction the graph actually escalated."""

    citation_faithfulness: float
    """Fraction of cases where all coverage citations were grounded in retrieved context."""

    tool_call_accuracy: float
    """Fraction of cases where all expected MCP tool calls were observed in the trace."""

    # Latency
    p50_latency_ms: float
    p95_latency_ms: float

    # Cost proxy (token counts from fake LLM)
    avg_prompt_tokens: float
    avg_completion_tokens: float
    # M9: cost estimate derived from token counts (Decimal → string in JSON mode)
    avg_cost_usd: Decimal = Field(default=Decimal(0))

    # CI gate
    gate_passed: bool
    gate_failures: list[str] = Field(default_factory=list)

    case_results: list[CaseResult]


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def compute_scorecard(results: list[CaseResult]) -> Scorecard:
    """Aggregate per-case results into a :class:`Scorecard` and check the CI gate."""
    n = len(results)
    if n == 0:
        return Scorecard(
            total_cases=0,
            passed=0,
            failed=0,
            decision_accuracy=0.0,
            escalation_precision=0.0,
            escalation_recall=0.0,
            citation_faithfulness=0.0,
            tool_call_accuracy=0.0,
            p50_latency_ms=0.0,
            p95_latency_ms=0.0,
            avg_prompt_tokens=0.0,
            avg_completion_tokens=0.0,
            gate_passed=False,
            gate_failures=["No cases evaluated"],
            case_results=[],
        )

    passed_count = sum(1 for r in results if r.passed)

    # --- Core accuracy metrics ---
    decision_accuracy = sum(1 for r in results if r.disposition_correct) / n
    citation_faithfulness = sum(1 for r in results if r.citations_faithful) / n
    tool_call_accuracy = sum(1 for r in results if r.tool_calls_correct) / n

    # --- Escalation precision / recall ---
    # TP: expected escalated AND graph escalated
    tp = sum(
        1
        for r in results
        if r.expected_disposition == "escalated" and r.actual_disposition == "escalated"
    )
    # FP: expected NOT escalated BUT graph escalated
    fp = sum(
        1
        for r in results
        if r.expected_disposition != "escalated" and r.actual_disposition == "escalated"
    )
    # FN: expected escalated BUT graph did NOT escalate
    fn = sum(
        1
        for r in results
        if r.expected_disposition == "escalated" and r.actual_disposition != "escalated"
    )
    escalation_precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    escalation_recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0

    # --- Latency percentiles ---
    latencies = sorted(r.latency_ms for r in results)
    p50 = statistics.median(latencies)
    p95_idx = max(0, int(0.95 * n) - 1)
    p95 = latencies[p95_idx]

    # --- Token averages and cost estimate ---
    avg_prompt = sum(r.prompt_tokens for r in results) / n
    avg_completion = sum(r.completion_tokens for r in results) / n
    avg_cost = sum(
        _COST_PER_PROMPT * Decimal(r.prompt_tokens)
        + _COST_PER_COMPLETION * Decimal(r.completion_tokens)
        for r in results
    ) / Decimal(n)

    # --- Gate checks ---
    gate_failures: list[str] = []
    _check(gate_failures, "decision_accuracy", decision_accuracy, GATE_DECISION_ACCURACY)
    _check(  # long name on its own line to stay within 100 chars
        gate_failures, "citation_faithfulness", citation_faithfulness, GATE_CITATION_FAITHFULNESS
    )
    _check(gate_failures, "tool_call_accuracy", tool_call_accuracy, GATE_TOOL_CALL_ACCURACY)
    _check(gate_failures, "escalation_precision", escalation_precision, GATE_ESCALATION_PRECISION)
    _check(gate_failures, "escalation_recall", escalation_recall, GATE_ESCALATION_RECALL)

    return Scorecard(
        total_cases=n,
        passed=passed_count,
        failed=n - passed_count,
        decision_accuracy=decision_accuracy,
        escalation_precision=escalation_precision,
        escalation_recall=escalation_recall,
        citation_faithfulness=citation_faithfulness,
        tool_call_accuracy=tool_call_accuracy,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
        avg_prompt_tokens=avg_prompt,
        avg_completion_tokens=avg_completion,
        avg_cost_usd=avg_cost,
        gate_passed=not gate_failures,
        gate_failures=gate_failures,
        case_results=results,
    )


def _check(failures: list[str], name: str, actual: float, threshold: float) -> None:
    """Append a failure message if *actual* is below *threshold*."""
    if actual < threshold:
        failures.append(f"{name} {actual:.2%} < gate {threshold:.0%}")
