"""Coverage-decision agent — the reference pattern for all ClaimPilot agents.

Pure async function: ``(ClaimFacts, PolicyContext, LLMClient) → CoverageOpinion``.
No global state, no direct provider imports.
"""

from __future__ import annotations

import json
from typing import Any

from claimpilot.agents.prompts.coverage import SYSTEM_PROMPT, build_user_prompt
from claimpilot.infra.interfaces import LLMClient
from claimpilot.models.claim import ClaimFacts
from claimpilot.models.common import Citation
from claimpilot.models.decisions import CoverageOpinion, PolicyContext
from claimpilot.models.trace import AgentError

# Confidence is capped at this value when retrieval is weak
# (≤ 1 citation in context), regardless of model assertiveness.
_CONFIDENCE_CAP_WEAK = 0.6


class CoverageAgentError(Exception):
    """Raised by the coverage agent on irrecoverable error.

    Carries a typed ``AgentError`` for the graph's error_handler node.
    """

    def __init__(self, error: AgentError) -> None:
        self.error = error
        super().__init__(error.message)


async def decide(
    facts: ClaimFacts,
    context: PolicyContext,
    *,
    llm: LLMClient,
) -> CoverageOpinion:
    """Decide coverage for *facts* against *context*.

    Spec: ``docs/specs/20-agent-coverage.md``.
    """
    # ── 1. Insufficient-context guard (no LLM call) ──────────────────
    if not context.sufficient:
        return CoverageOpinion(
            decision="partial",
            confidence=0.1,
            rationale="Insufficient policy context for a grounded coverage decision.",
            citations=context.citations[:1],
        )

    # ── 2. Build grounded prompt ──────────────────────────────────────
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(facts, context)},
    ]

    # ── 3. Call LLM with structured output ────────────────────────────
    try:
        response = await llm.generate(messages, response_schema=CoverageOpinion)
        raw = json.loads(response["content"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CoverageAgentError(
            AgentError(
                node="coverage_decision",
                error_type="MalformedOutput",
                message=f"Could not parse LLM response: {exc}",
            )
        ) from exc

    if not isinstance(raw, dict):
        raise CoverageAgentError(
            AgentError(
                node="coverage_decision",
                error_type="MalformedOutput",
                message=f"Expected JSON object, got {type(raw).__name__}",
            )
        )

    # ── 4. Extract and validate fields ────────────────────────────────
    decision = _validated_decision(raw)
    confidence = _clamp(raw.get("confidence", 0.5))
    rationale = str(raw.get("rationale", "")) or "No rationale provided."
    raw_citations: Any = raw.get("citations", [])

    # ── 5. Citation enforcement ───────────────────────────────────────
    valid_clause_ids = {c.clause_id for c in context.citations}
    valid_citations = _filter_citations(raw_citations, valid_clause_ids)

    if not valid_citations:
        # All model citations were hallucinated → escalate.
        return CoverageOpinion(
            decision="partial",
            confidence=0.1,
            rationale="All model citations were invalid; escalating for human review.",
            citations=context.citations[:1],
        )

    # ── 6. Confidence cap on weak retrieval ───────────────────────────
    confidence = _cap_confidence(confidence, context)

    return CoverageOpinion(
        decision=decision,
        confidence=confidence,
        rationale=rationale,
        citations=valid_citations,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_DECISIONS = frozenset({"covered", "denied", "partial"})


def _validated_decision(raw: dict[str, Any]) -> str:
    """Extract ``decision`` from *raw*, defaulting to ``"partial"``."""
    d = raw.get("decision", "partial")
    if d not in _VALID_DECISIONS:
        return "partial"
    return str(d)


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp *value* to [lo, hi], coercing to float."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(lo, min(hi, v))


def _filter_citations(
    raw_citations: Any,
    valid_ids: set[str],
) -> list[Citation]:
    """Keep only citations whose ``clause_id`` exists in *valid_ids*."""
    if not isinstance(raw_citations, list):
        return []
    result: list[Citation] = []
    for rc in raw_citations:
        if not isinstance(rc, dict):
            continue
        if rc.get("clause_id") not in valid_ids:
            continue
        try:
            result.append(Citation(**rc))
        except Exception:  # noqa: BLE001, S112
            continue
    return result


def _cap_confidence(confidence: float, context: PolicyContext) -> float:
    """Cap confidence when retrieval is weak (≤ 1 citation)."""
    if len(context.citations) <= 1:
        return min(confidence, _CONFIDENCE_CAP_WEAK)
    return confidence
