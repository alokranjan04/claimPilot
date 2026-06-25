"""Settlement-computation agent.

Pure async function: ``(ClaimFacts, CoverageOpinion, LLMClient) → SettlementProposal``.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from claimpilot.agents.prompts.settlement import SYSTEM_PROMPT, build_user_prompt
from claimpilot.infra.interfaces import LLMClient
from claimpilot.models.claim import ClaimFacts
from claimpilot.models.common import LineItem
from claimpilot.models.decisions import CoverageOpinion, SettlementProposal
from claimpilot.models.trace import AgentError


class SettlementAgentError(Exception):
    """Raised by the settlement agent on irrecoverable error."""

    def __init__(self, error: AgentError) -> None:
        self.error = error
        super().__init__(error.message)


async def compute(
    facts: ClaimFacts,
    coverage: CoverageOpinion,
    *,
    llm: LLMClient,
) -> SettlementProposal:
    """Compute a settlement proposal for *facts* given *coverage*.

    Spec: master-spec §4 — Settlement agent row.
    """
    # Denied coverage → zero settlement.
    if coverage.decision == "denied":
        return SettlementProposal(
            payable_amount=Decimal(0),
            deductible_applied=Decimal(0),
            limit_applied=facts.claimed_amount,
            breakdown=[LineItem(description="Coverage denied", amount=Decimal(0))],
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(facts, coverage)},
    ]

    try:
        response = await llm.generate(messages, response_schema=SettlementProposal)
        raw = json.loads(response["content"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SettlementAgentError(
            AgentError(
                node="settlement",
                error_type="MalformedOutput",
                message=f"Could not parse LLM response: {exc}",
            )
        ) from exc

    if not isinstance(raw, dict):
        raise SettlementAgentError(
            AgentError(
                node="settlement",
                error_type="MalformedOutput",
                message=f"Expected JSON object, got {type(raw).__name__}",
            )
        )

    payable = _to_decimal(raw.get("payable_amount", "0"))
    deductible = _to_decimal(raw.get("deductible_applied", "0"))
    limit = _to_decimal(raw.get("limit_applied", str(facts.claimed_amount)))
    breakdown = _extract_breakdown(raw.get("breakdown", []))

    if not breakdown:
        breakdown = [LineItem(description="Claim payment", amount=payable)]

    # Enforce payable ≤ limit (the model validator would catch this, but we
    # prefer to clamp rather than crash).
    if limit > Decimal(0) and payable > limit:
        payable = limit

    return SettlementProposal(
        payable_amount=payable,
        deductible_applied=deductible,
        limit_applied=limit,
        breakdown=breakdown,
    )


def _to_decimal(value: Any) -> Decimal:
    """Coerce *value* to Decimal, defaulting to 0."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _extract_breakdown(raw: Any) -> list[LineItem]:
    """Parse a list of line-item dicts, tolerating bad data."""
    if not isinstance(raw, list):
        return []
    items: list[LineItem] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        desc = str(entry.get("description", ""))
        if not desc:
            continue
        amt = _to_decimal(entry.get("amount", "0"))
        items.append(LineItem(description=desc, amount=amt))
    return items
