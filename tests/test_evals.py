"""Tests for the M7 evaluation harness.

Covers:
  1. compute_scorecard — unit tests with synthetic CaseResults.
  2. GoldenDataset loading — verifies cases.json parses cleanly.
  3. Integration smoke test — runs two cases from the golden dataset end-to-end.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `evals` is importable.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evals.metrics import (  # noqa: E402
    CaseResult,
    EvalCase,
    GoldenDataset,
    compute_scorecard,
)
from evals.run_evals import _load_dataset, _run_case  # noqa: E402

_GOLDEN_PATH = _ROOT / "evals" / "golden" / "cases.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    *,
    case_id: str = "T-001",
    passed: bool = True,
    expected: str = "auto_approved",
    actual: str = "auto_approved",
    citations_faithful: bool = True,
    tool_calls_correct: bool = True,
    latency_ms: float = 50.0,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        passed=passed,
        expected_disposition=expected,
        actual_disposition=actual,
        disposition_correct=(expected == actual),
        citations_faithful=citations_faithful,
        tool_calls_correct=tool_calls_correct,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        failures=[] if passed else ["synthetic failure"],
    )


# ---------------------------------------------------------------------------
# Unit: compute_scorecard
# ---------------------------------------------------------------------------


class TestComputeScorecard:
    def test_empty_returns_gate_failed(self) -> None:
        sc = compute_scorecard([])
        assert sc.gate_passed is False
        assert sc.total_cases == 0

    def test_perfect_score_passes_gate(self) -> None:
        """All cases passing with faithful citations → gate green."""
        results = [
            _result(case_id=f"T-{i:03}", expected="auto_approved", actual="auto_approved")
            for i in range(5)
        ]
        sc = compute_scorecard(results)
        assert sc.decision_accuracy == 1.0
        assert sc.citation_faithfulness == 1.0
        assert sc.tool_call_accuracy == 1.0
        assert sc.gate_passed is True
        assert sc.passed == 5
        assert sc.failed == 0

    def test_decision_accuracy_below_gate(self) -> None:
        """50% accuracy should fail the gate (threshold 90%)."""
        results = [
            _result(expected="auto_approved", actual="auto_approved"),
            _result(expected="auto_approved", actual="escalated", passed=False),
        ]
        sc = compute_scorecard(results)
        assert sc.decision_accuracy == 0.5
        assert sc.gate_passed is False
        assert any("decision_accuracy" in f for f in sc.gate_failures)

    def test_citation_faithfulness_gate(self) -> None:
        """50% citation faithfulness fails the gate (threshold 90%)."""
        results = [
            _result(citations_faithful=True),
            _result(citations_faithful=False, passed=False),
        ]
        sc = compute_scorecard(results)
        assert sc.citation_faithfulness == 0.5
        assert sc.gate_passed is False

    def test_escalation_precision_recall(self) -> None:
        """Verify precision/recall calculation."""
        results = [
            # TP: expected escalated, got escalated
            _result(expected="escalated", actual="escalated"),
            # FP: expected auto_approved, but got escalated (over-escalation)
            _result(expected="auto_approved", actual="escalated", passed=False),
            # FN: expected escalated, got auto_approved (missed escalation)
            _result(expected="escalated", actual="auto_approved", passed=False),
        ]
        sc = compute_scorecard(results)
        # TP=1, FP=1, FN=1
        # precision = 1/(1+1) = 0.5
        # recall    = 1/(1+1) = 0.5
        assert abs(sc.escalation_precision - 0.5) < 1e-9
        assert abs(sc.escalation_recall - 0.5) < 1e-9
        assert sc.gate_passed is False

    def test_escalation_precision_perfect_when_no_fp(self) -> None:
        results = [
            _result(expected="escalated", actual="escalated"),
            _result(expected="auto_approved", actual="auto_approved"),
        ]
        sc = compute_scorecard(results)
        assert sc.escalation_precision == 1.0
        assert sc.escalation_recall == 1.0

    def test_latency_percentiles(self) -> None:
        latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        results = [_result(latency_ms=lat) for lat in latencies]
        sc = compute_scorecard(results)
        # p50 of [10..100] = 55.0 (median of 10 values)
        assert sc.p50_latency_ms == 55.0
        # p95 index = int(0.95 * 10) - 1 = 8 → latencies[8] = 90.0
        assert sc.p95_latency_ms == 90.0

    def test_token_averages(self) -> None:
        results = [
            _result(prompt_tokens=100, completion_tokens=50),
            _result(prompt_tokens=200, completion_tokens=100),
        ]
        sc = compute_scorecard(results)
        assert sc.avg_prompt_tokens == 150.0
        assert sc.avg_completion_tokens == 75.0

    def test_no_escalation_cases_precision_defaults_to_1(self) -> None:
        """When no predicted escalations, precision defaults to 1 (not div-by-zero)."""
        results = [_result(expected="auto_approved", actual="auto_approved")]
        sc = compute_scorecard(results)
        assert sc.escalation_precision == 1.0
        assert sc.escalation_recall == 1.0


# ---------------------------------------------------------------------------
# Unit: GoldenDataset loading
# ---------------------------------------------------------------------------


class TestGoldenDataset:
    def test_cases_json_parses(self) -> None:
        """cases.json must parse into a valid GoldenDataset."""
        raw = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
        dataset = GoldenDataset.model_validate(raw)
        assert len(dataset.corpus) >= 1
        assert len(dataset.cases) >= 10

    def test_all_cases_have_required_fields(self) -> None:
        raw = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
        dataset = GoldenDataset.model_validate(raw)
        for case in dataset.cases:
            assert case.id
            assert case.description
            assert case.claim.get("claim_id")
            assert case.claim.get("policy_number")
            assert case.claim.get("fnol_text")
            assert case.expected.disposition in {"auto_approved", "auto_denied", "escalated"}

    def test_dataset_covers_all_disposition_types(self) -> None:
        """Golden set must include auto_approved, auto_denied, and escalated cases."""
        raw = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
        dataset = GoldenDataset.model_validate(raw)
        dispositions = {c.expected.disposition for c in dataset.cases}
        assert "auto_approved" in dispositions
        assert "auto_denied" in dispositions
        assert "escalated" in dispositions

    def test_load_dataset_helper(self) -> None:
        corpus, cases = _load_dataset()
        assert len(corpus) >= 1
        assert len(cases) >= 10
        assert all(isinstance(c, EvalCase) for c in cases)


# ---------------------------------------------------------------------------
# Integration smoke: run two golden cases end-to-end
# ---------------------------------------------------------------------------


class TestEvalRunner:
    async def test_auto_approve_case_passes(self) -> None:
        """EVL-001 (clean auto-approve) must produce a passing CaseResult."""
        corpus, cases = _load_dataset()
        case = next(c for c in cases if c.id == "EVL-001")
        res = await _run_case(case, corpus)

        assert res.case_id == "EVL-001"
        assert res.disposition_correct is True
        assert res.actual_disposition == "auto_approved"
        assert res.citations_faithful is True
        assert res.tool_calls_correct is True
        assert res.passed is True
        assert res.latency_ms > 0

    async def test_escalation_case_passes(self) -> None:
        """EVL-002 (high-amount escalation) must produce a passing CaseResult."""
        corpus, cases = _load_dataset()
        case = next(c for c in cases if c.id == "EVL-002")
        res = await _run_case(case, corpus)

        assert res.case_id == "EVL-002"
        assert res.actual_disposition == "escalated"
        assert res.disposition_correct is True
        assert res.citations_faithful is True
        assert res.passed is True

    async def test_auto_deny_case_passes(self) -> None:
        """EVL-006 (denied-coverage → auto_denied) must pass."""
        corpus, cases = _load_dataset()
        case = next(c for c in cases if c.id == "EVL-006")
        res = await _run_case(case, corpus)

        assert res.actual_disposition == "auto_denied"
        assert res.disposition_correct is True
        assert res.passed is True

    async def test_insufficient_context_case_passes(self) -> None:
        """EVL-010 (insufficient RAG context) escalates correctly."""
        corpus, cases = _load_dataset()
        case = next(c for c in cases if c.id == "EVL-010")
        res = await _run_case(case, corpus)

        assert res.actual_disposition == "escalated"
        assert res.disposition_correct is True
        assert res.passed is True

    async def test_full_scorecard_passes_gate(self) -> None:
        """Running all 10 cases must produce a gate-passing scorecard."""
        from evals.run_evals import _run_all

        corpus, cases = _load_dataset()
        results = await _run_all(cases, corpus)
        scorecard = compute_scorecard(results)

        assert scorecard.total_cases == 10
        assert scorecard.gate_passed is True, (
            f"Gate failed: {scorecard.gate_failures}\n"
            + "\n".join(
                f"  {r.case_id}: {r.failures}" for r in scorecard.case_results if not r.passed
            )
        )
