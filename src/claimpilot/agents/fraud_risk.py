"""Fraud/risk-scoring agent.

Pure async function: ``(ClaimFacts, LLMClient, [tools]) → RiskAssessment``.
Optionally consults claims_history and fraud_signals MCP tools.
"""

from __future__ import annotations

import json
from typing import Any

from claimpilot.agents.prompts.fraud_risk import SYSTEM_PROMPT, build_user_prompt
from claimpilot.infra.interfaces import LLMClient
from claimpilot.mcp_servers.base import AuthContext
from claimpilot.mcp_servers.claims_history import ClaimsHistoryServer
from claimpilot.mcp_servers.fraud_signals import FraudSignalsServer
from claimpilot.models.claim import ClaimFacts
from claimpilot.models.decisions import RiskAssessment
from claimpilot.models.trace import AgentError

_AUTH = AuthContext(caller="fraud_risk_agent", scopes=["claims_history.read", "fraud_signals.read"])


class FraudRiskAgentError(Exception):
    """Raised by the fraud-risk agent on irrecoverable error."""

    def __init__(self, error: AgentError) -> None:
        self.error = error
        super().__init__(error.message)


async def assess(
    facts: ClaimFacts,
    *,
    llm: LLMClient,
    claims_history: ClaimsHistoryServer | None = None,
    fraud_signals: FraudSignalsServer | None = None,
) -> RiskAssessment:
    """Score fraud risk for *facts*, optionally enriched by MCP tools.

    When *claims_history* or *fraud_signals* servers are provided, the agent
    queries them and includes the results in the LLM prompt for a richer
    assessment.  The tool results are also used as a floor signal.
    """
    tool_context = ""
    tool_score: float | None = None

    # ── MCP tool calls (optional enrichment) ─────────────────────────
    if claims_history is not None:
        claimant_name = facts.parties[0].name if facts.parties else ""
        record = claims_history.lookup(claimant_name, auth=_AUTH)
        if record:
            tool_context += (
                f"\n## Claims History (via MCP)\n"
                f"- Claimant: {record.name}\n"
                f"- Total prior claims: {record.total_claims}\n"
                f"- Flagged: {record.flagged}\n"
            )

    if fraud_signals is not None:
        claimant_name = facts.parties[0].name if facts.parties else ""
        record_for_score = (
            claims_history.lookup(claimant_name, auth=_AUTH) if claims_history else None
        )
        fs = fraud_signals.score(
            incident_type=facts.incident_type,
            claimed_amount=str(facts.claimed_amount),
            claimant_name=claimant_name,
            prior_claim_count=record_for_score.total_claims if record_for_score else 0,
            flagged=record_for_score.flagged if record_for_score else False,
            auth=_AUTH,
        )
        tool_score = fs.score
        if fs.signals:
            tool_context += "\n## Fraud Signals (via MCP)\n"
            for sig in fs.signals:
                tool_context += f"- {sig.name} (weight={sig.weight}): {sig.detail}\n"

    # ── Build prompt ─────────────────────────────────────────────────
    user_prompt = build_user_prompt(facts)
    if tool_context:
        user_prompt += tool_context

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
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
    # Use the higher of LLM score and tool-computed score.
    if tool_score is not None:
        score = max(score, tool_score)
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
