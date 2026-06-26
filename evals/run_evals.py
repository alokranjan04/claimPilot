"""ClaimPilot evaluation runner — spec master-spec §11.

Usage::

    uv run python evals/run_evals.py           # human-readable scorecard + exit code
    uv run python evals/run_evals.py --json    # JSON scorecard to stdout
    uv run python evals/run_evals.py --quiet   # only print gate result

Exit code 0 if all CI gate metrics pass; exit code 1 on regression (blocks merge).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# Ensure the project root is on sys.path when run directly as a script.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from claimpilot.graph.build_graph import build_graph  # noqa: E402
from claimpilot.infra.providers.fakes import (  # noqa: E402
    FakeEmbedder,
    FakeLLMClient,
    FakeReranker,
    FakeVectorStore,
)
from claimpilot.infra.settings import Settings  # noqa: E402
from claimpilot.models.claim import RawClaim  # noqa: E402
from claimpilot.rag.models import SourceDoc  # noqa: E402
from claimpilot.rag.pipeline import RagPipeline  # noqa: E402
from evals.metrics import (  # noqa: E402
    CaseResult,
    EvalCase,
    GoldenDataset,
    Scorecard,
    compute_scorecard,
)

_GOLDEN_PATH = Path(__file__).parent / "golden" / "cases.json"


# ---------------------------------------------------------------------------
# Token-counting LLM wrapper (satisfies the LLMClient protocol)
# ---------------------------------------------------------------------------


class _CountingLLM:
    """Delegates to a :class:`FakeLLMClient` and accumulates token counts."""

    def __init__(self, inner: FakeLLMClient) -> None:
        self._inner = inner
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_schema: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        """Delegate to inner LLM and accumulate token usage."""
        result = await self._inner.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_schema=response_schema,
        )
        usage = result.get("usage", {})
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        return result


# ---------------------------------------------------------------------------
# Per-case runner
# ---------------------------------------------------------------------------


async def _run_case(case: EvalCase, corpus: list[SourceDoc]) -> CaseResult:
    """Run one golden eval case end-to-end through the graph.

    Returns a :class:`CaseResult` with all metric fields populated.
    """
    settings = Settings(rag_tau_sufficient=case.rag_tau_sufficient)

    rag = RagPipeline(
        embedder=FakeEmbedder(dims=64, seed=42),
        vector_store=FakeVectorStore(),
        reranker=FakeReranker(),
        settings=settings,
    )
    await rag.ingest(corpus)

    fake_llm = FakeLLMClient(scripted=list(case.llm_scripted))
    counting_llm = _CountingLLM(fake_llm)

    graph = build_graph(settings, llm=counting_llm, rag=rag)
    raw = RawClaim(**case.claim)

    t0 = time.perf_counter()
    try:
        result = await graph.ainvoke({"claim_id": raw.claim_id, "raw_input": raw})
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return CaseResult(
            case_id=case.id,
            passed=False,
            expected_disposition=case.expected.disposition,
            actual_disposition=None,
            disposition_correct=False,
            citations_faithful=False,
            tool_calls_correct=False,
            latency_ms=latency_ms,
            prompt_tokens=counting_llm.prompt_tokens,
            completion_tokens=counting_llm.completion_tokens,
            failures=[f"Graph raised exception: {exc}"],
        )
    latency_ms = (time.perf_counter() - t0) * 1000.0

    # ── Disposition ──────────────────────────────────────────────────────────
    actual_disposition: str | None = result.get("disposition")
    disposition_correct = actual_disposition == case.expected.disposition

    failures: list[str] = []
    if not disposition_correct:
        failures.append(
            f"disposition: expected={case.expected.disposition!r} actual={actual_disposition!r}"
        )

    # ── Coverage ─────────────────────────────────────────────────────────────
    coverage = result.get("coverage")
    coverage_decision: str | None = coverage.decision if coverage else None
    coverage_correct: bool | None = None
    if case.expected.coverage_decision is not None and coverage is not None:
        coverage_correct = coverage.decision == case.expected.coverage_decision
        if not coverage_correct:
            failures.append(
                f"coverage_decision: expected={case.expected.coverage_decision!r} "
                f"actual={coverage_decision!r}"
            )

    # ── Citation faithfulness ────────────────────────────────────────────────
    # Every clause_id cited by the coverage agent must appear in the retrieved
    # policy context — no hallucinated citations.
    policy_ctx = result.get("policy_context")
    citations_faithful = True
    if coverage and policy_ctx:
        valid_ids = {c.clause_id for c in policy_ctx.citations}
        for cit in coverage.citations:
            if cit.clause_id not in valid_ids:
                citations_faithful = False
                failures.append(f"Hallucinated citation: {cit.clause_id!r}")

    # ── Tool-call correctness ────────────────────────────────────────────────
    expected_tools = set(case.expected.expects_tool_calls)
    tool_calls_correct = True
    if expected_tools:
        found_tools: set[str] = set()
        for trace_step in result.get("trace", []):
            for tool in trace_step.inputs.get("tool_calls", []):
                found_tools.add(tool)
        missing = expected_tools - found_tools
        if missing:
            tool_calls_correct = False
            failures.append(f"Missing MCP tool calls: {sorted(missing)}")

    passed = disposition_correct and citations_faithful and tool_calls_correct

    return CaseResult(
        case_id=case.id,
        passed=passed,
        expected_disposition=case.expected.disposition,
        actual_disposition=actual_disposition,
        disposition_correct=disposition_correct,
        coverage_decision=coverage_decision,
        coverage_correct=coverage_correct,
        citations_faithful=citations_faithful,
        tool_calls_correct=tool_calls_correct,
        latency_ms=latency_ms,
        prompt_tokens=counting_llm.prompt_tokens,
        completion_tokens=counting_llm.completion_tokens,
        failures=failures,
    )


# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------


def _load_dataset() -> tuple[list[SourceDoc], list[EvalCase]]:
    """Load the golden dataset from ``evals/golden/cases.json``."""
    raw = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    dataset = GoldenDataset.model_validate(raw)
    corpus = [SourceDoc(**doc) for doc in dataset.corpus]
    return corpus, dataset.cases


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def _run_all(cases: list[EvalCase], corpus: list[SourceDoc]) -> list[CaseResult]:
    """Run all eval cases sequentially and collect results."""
    results: list[CaseResult] = []
    for case in cases:
        result = await _run_case(case, corpus)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _print_scorecard(scorecard: Scorecard, *, quiet: bool = False) -> None:
    """Emit a human-readable scorecard to stdout."""
    if not quiet:
        print("\n" + "=" * 62)
        print(" ClaimPilot Eval Scorecard")
        print("=" * 62)
        print(f"  Total cases         : {scorecard.total_cases}")
        print(f"  Passed              : {scorecard.passed}")
        print(f"  Failed              : {scorecard.failed}")
        print()
        print(f"  Decision accuracy   : {scorecard.decision_accuracy:.1%}")
        print(f"  Escalation prec.    : {scorecard.escalation_precision:.1%}")
        print(f"  Escalation recall   : {scorecard.escalation_recall:.1%}")
        print(f"  Citation faithfulness: {scorecard.citation_faithfulness:.1%}")
        print(f"  Tool-call accuracy  : {scorecard.tool_call_accuracy:.1%}")
        print()
        print(f"  Latency p50         : {scorecard.p50_latency_ms:.1f} ms")
        print(f"  Latency p95         : {scorecard.p95_latency_ms:.1f} ms")
        print(f"  Avg prompt tokens   : {scorecard.avg_prompt_tokens:.0f}")
        print(f"  Avg completion tok. : {scorecard.avg_completion_tokens:.0f}")
        print(f"  Avg cost (est.)     : ${scorecard.avg_cost_usd:.6f}")
        print()

        for res in scorecard.case_results:
            status = "PASS" if res.passed else "FAIL"
            disp = res.actual_disposition or "?"
            line = f"  [{status}] {res.case_id} | disp={disp} | {res.latency_ms:.0f}ms"
            if res.failures:
                line += " | " + "; ".join(res.failures)
            print(line)

        print()

    if scorecard.gate_passed:
        print("CI GATE: PASSED")
    else:
        print("CI GATE: FAILED")
        for msg in scorecard.gate_failures:
            print(f"  x {msg}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the eval harness and exit with the gate result."""
    parser = argparse.ArgumentParser(description="ClaimPilot evaluation harness.")
    parser.add_argument("--json", action="store_true", help="Emit JSON scorecard to stdout.")
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress per-case details; print gate only."
    )
    args = parser.parse_args()

    corpus, cases = _load_dataset()
    results = asyncio.run(_run_all(cases, corpus))
    scorecard = compute_scorecard(results)

    if args.json:
        print(scorecard.model_dump_json(indent=2))
    else:
        _print_scorecard(scorecard, quiet=args.quiet)

    sys.exit(0 if scorecard.gate_passed else 1)


if __name__ == "__main__":
    main()
