"""Fraud/risk-scoring agent.

Pure async function: ``(ClaimFacts, LLMClient) → RiskAssessment``.
"""

from __future__ import annotations

import json
from typing import Any

from claimpilot.agents.prompts.fraud_risk import SYSTEM_PROMPT, build_user_prompt
from claimpilot.infra.interfaces import LLMClient
from claimpilot.models.claim import ClaimFacts
from claimpilot.models.decisions import RiskAssessment
from claimpilot.models.trace import AgentError


class FraudRiskAgentError(Exception):
    """Raised by the fraud-risk agent on irrecoverable error."""

    def __init__(self, error: AgentError) -> None:
        self.error = error
        super().__init__(error.message)


async def assess(
    facts: ClaimFacts,
    *,
    llm: LLMClient,
) -> RiskAssessment:
    """Score fraud risk for *facts*.

    Spec: master-spec §4 — Fraud/Risk agent row.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(facts)},
    ]

    try:
        response = await llm.generate(messages, response_schema=RiskAssessment)
        raw = json.loads(response["content"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise FraudRiskAgentError(
            AgentError(
                node="fraud_risk",
                error_type="MalformedOutput",
                message=f"Could not parse LLM response: {exc}",
            )
        ) from exc

    if not isinstance(raw, dict):
        raise FraudRiskAgentError(
            AgentError(
                node="fraud_risk",
                error_type="MalformedOutput",
                message=f"Expected JSON object, got {type(raw).__name__}",
            )
        )

    score = _clamp(raw.get("score", 0.5))
    signals = _extract_signals(raw.get("signals", []))
    recommendation = str(raw.get("recommendation", "")) or "No recommendation provided."

    return RiskAssessment(
        score=score,
        signals=signals,
        recommendation=recommendation,
    )


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp *value* to [lo, hi], coercing to float."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(lo, min(hi, v))


def _extract_signals(raw: Any) -> list[str]:
    """Extract a list of string signals, tolerating bad data."""
    if not isinstance(raw, list):
        return []
    return [str(s) for s in raw if s]
