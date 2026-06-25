# Component Spec — Coverage-Decision Agent (M5)

**Drives:** M5 (the hardest agent) · **Code:** `src/claimpilot/agents/coverage.py` (+ prompt) · **Depends on:** `LLMClient` (M2); `PolicyContext`, `CoverageOpinion`, `Citation`, `ClaimFacts` (M1); RAG pipeline (M4).

## Purpose
Decide whether a claim is **covered, denied, or partial** against the retrieved policy context, with a rationale and citations strong enough to survive audit. This is the decision the whole system pivots on, so it must be grounded, conservative, and explicit about uncertainty.

## Inputs / Outputs (typed)
```
async def decide(facts: ClaimFacts, context: PolicyContext) -> CoverageOpinion
```
- Input `context` carries the retrieved chunks + `sufficient` flag from M4.
- Output is the M1 `CoverageOpinion`: `{decision, confidence∈[0,1], rationale, citations: non-empty}`.

## Behavior
1. **Insufficient-context guard (first).** If `context.sufficient is False`, return immediately: `decision="partial"`-or-escalate signal with low `confidence` and a rationale of "insufficient policy context"; do **not** call the LLM to invent an answer. (The graph routes low-confidence to human escalation.)
2. **Grounded prompt.** Build a prompt that includes only the retrieved chunks, instructs the model to decide using *only* that context, to cite the `clause_id`s it relied on, and to say so when the policy is silent.
3. **Structured output.** Call `LLMClient` with the `CoverageOpinion` schema (structured/JSON output). In tests the fake LLM returns scripted structured responses keyed to the fixture.
4. **Citation enforcement.** Every cited `clause_id` in the output **must** exist in `context.chunks`. Drop hallucinated citations; if that empties the citation list, downgrade to low-confidence escalation. (`CoverageOpinion`'s M1 validator already rejects empty citations — handle it before constructing the model, don't let it throw.)
5. **Confidence calibration.** Map model signal + retrieval strength into `confidence`; weak retrieval caps confidence regardless of model assertiveness.
6. **Purity.** The agent is a pure async function of its inputs + injected `LLMClient` — no global state, no direct provider import — so it's unit-testable with the fake.

## Prompt strategy (keep in the prompt file, version it)
- System: role = conservative insurance coverage adjudicator; rules = answer only from provided clauses, cite clause IDs, prefer "partial/escalate" over guessing, never invent exclusions.
- User: structured `ClaimFacts` + the retrieved clauses (each with its `clause_id`).
- Require: `decision`, `confidence`, `rationale` referencing clause IDs, `citations`.

## Edge cases (must handle explicitly)
- **`sufficient=False`** → no LLM call; low-confidence escalation. (Test this path.)
- **Model cites a clause not in context** → strip it; recompute; possibly escalate.
- **Model returns all citations invalid** → escalate, don't raise.
- **Conflicting clauses** (one covers, one excludes) → `partial` with both cited and rationale explaining the conflict.
- **Claimed amount missing/zero** → still decide coverage; flag amount issue for the settlement agent (don't crash).
- **Non-deterministic LLM in prod** → tests use the fake; never assert on live-model wording, only on the structured fields.
- **Malformed structured output** → typed `AgentError` (caught by graph error_handler), not a bare exception.

## Acceptance tests (with fake LLM)
- [ ] Covered case: fixture with a matching coverage clause → `decision="covered"`, citations subset of context, confidence high.
- [ ] Denied case: fixture with an exclusion → `decision="denied"`, exclusion cited.
- [ ] Partial/conflict: covering + excluding clauses → `decision="partial"`, both cited.
- [ ] Insufficient context: `context.sufficient=False` → no LLM call (assert the fake wasn't invoked), low confidence, escalation signal.
- [ ] Hallucinated citation stripped: fake returns a `clause_id` absent from context → it's removed; behavior matches rule 4.
- [ ] Confidence cap: weak retrieval → confidence bounded below threshold even if model is assertive.
- [ ] `AgentError` on malformed fake output; graph stays alive.
- [ ] mypy strict + ruff clean; agent imports no concrete provider.

## Done means
The coverage agent is the reference pattern for the other agents (fraud, settlement, compliance): grounded prompt → structured output → citation/validity enforcement → typed errors → pure & testable. Build it carefully; the rest copy its shape.
