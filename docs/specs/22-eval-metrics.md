# Component Spec — Evaluation Harness & Metrics (M7)

**Drives:** M7 · **Code:** `evals/` · **Depends on:** a runnable graph over fakes (M3+), `ClaimState`/`trace` (M1).

## Purpose
Make quality measurable and regressions impossible to merge silently. The harness runs the graph over a labeled golden dataset, scores it on defined metrics, and emits a scorecard that a CI gate enforces. This is the project's differentiator — treat evals as the test suite for non-deterministic software.

## Inputs / Outputs (typed)
```
run_evals(dataset: GoldenSet, thresholds: Thresholds) -> Scorecard
```
- `GoldenCase`: `{claim_id, raw_claim, expected: {disposition, coverage_decision, expected_clause_ids: set[str], expected_payable_band: [lo,hi]}}`
- `Scorecard`: `{per_metric: dict[str,float], per_case: list[CaseResult], passed: bool, run_id, timestamp}` — persisted to `evals/results/` as JSON.

## Golden dataset
- 50–100 synthetic cases (no real PII). Cover: clean-covered, clean-denied, partial/conflict, insufficient-context, high-amount-escalation, fraud-flagged, malformed input.
- Stored in `evals/golden/` as JSON; each case carries its expected outcome. Versioned with the repo.

## Metrics (define exactly; all in [0,1] unless noted)
1. **Disposition accuracy** — fraction where `auto_approved/auto_denied/escalated` matches expected.
2. **Coverage-decision accuracy** — fraction where `covered/denied/partial` matches expected.
3. **Citation faithfulness** — of cited clause IDs, fraction that (a) exist in retrieved context AND (b) intersect `expected_clause_ids`. Penalize hallucinated citations hardest.
4. **Tool-call correctness** — fraction of expected tool calls made with valid args (from `trace`).
5. **Escalation precision / recall** — did it escalate exactly the cases that should escalate? Report both; F1 as the headline.
6. **Settlement accuracy** — fraction where `payable_amount` falls in `expected_payable_band`.
7. **Operational (report, not pass/fail unless set):** p50/p95 latency per claim, mean cost/claim — read from `trace`.

## Scoring methods
- **Deterministic assertions** for disposition, coverage, citations, tool calls, settlement band (no LLM judge needed — exact/structured comparisons). Prefer these; they're stable and free.
- **LLM-as-judge** only for open-ended rationale quality (optional secondary metric), calibrated against a few human labels; in CI runs use the fake/judge stub so the gate stays deterministic and offline.
- Faithfulness uses the structured citation comparison above (not a model) for determinism.

## CI gate (thresholds)
Default `Thresholds`: `disposition_accuracy>=0.90`, `coverage_accuracy>=0.90`, `citation_faithfulness>=0.95`, `tool_call_correctness>=0.95`, `escalation_f1>=0.85`, `settlement_accuracy>=0.90`. `Scorecard.passed = all metrics ≥ threshold`. CI fails the build when `passed is False` and prints the failing metrics + offending cases.

## Behavior
1. Load golden set; for each case run the graph (PROVIDER=fake) to a final `ClaimState`.
2. Score each metric from the final state + `trace` (the trace is the evidence source — this is why every node must append to it).
3. Aggregate into a `Scorecard`; write JSON to `evals/results/<run_id>.json`; print a human-readable table.
4. Exit non-zero if `passed is False` (so `make eval` / CI fails).

## Edge cases (must handle explicitly)
- **Case crashes mid-graph** → record as a failed case (disposition mismatch), don't abort the whole run.
- **Missing expected fields in a golden case** → fail fast at load with a clear message (bad fixture, not a model error).
- **Empty/biased golden set** → warn if any category (e.g., escalation cases) is unrepresented; coverage of categories is itself asserted.
- **Non-determinism** → with fakes, two runs produce identical scorecards; assert this in a meta-test.

## Acceptance tests
- [ ] `run_evals` over the golden set returns a `Scorecard` with all seven metrics computed.
- [ ] A deliberately broken agent (injected) drops the relevant metric below threshold and flips `passed=False`.
- [ ] CI job runs `evals/run_evals.py`, exits non-zero on regression, zero when green.
- [ ] Faithfulness penalizes a seeded hallucinated-citation case.
- [ ] Escalation precision/recall correct on the high-amount and insufficient-context cases.
- [ ] Determinism meta-test: identical scorecards across two runs.
- [ ] mypy strict + ruff clean.

## Forward note (M10+)
In production, swap the offline judge for **Azure AI Foundry Evaluation** (groundedness + custom evaluators) and log runs to the Foundry project / Azure Monitor. The deterministic structured metrics above stay as the hard CI gate; Foundry adds richer online/production evals.
