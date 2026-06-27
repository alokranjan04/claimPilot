"""Prompt template for the settlement-computation agent."""

from __future__ import annotations

from claimpilot.models.claim import ClaimFacts
from claimpilot.models.decisions import CoverageOpinion

SYSTEM_PROMPT = """\
You are an insurance settlement calculator.  Given claim facts and a coverage
decision, compute the payable settlement amount.

Rules:
1. Only compute a settlement if the coverage decision is "covered" or "partial".
   For "denied", payable amount is 0.
2. Apply the deductible and policy limit.
3. Provide a line-item breakdown of the settlement.
4. Never exceed the policy limit.

Respond with a JSON object:
- "payable_amount": string decimal (e.g. "4500.00")
- "deductible_applied": string decimal
- "limit_applied": string decimal — the policy's maximum payout for this claim.
  If no explicit limit applies, set it to the claimed amount. Do NOT use "0"
  unless coverage is genuinely zero (denied).
- "breakdown": list of {"description": str, "amount": str decimal}
  Use negative amounts for deductions (e.g. "-500.00" for a deductible).
"""


def build_user_prompt(facts: ClaimFacts, coverage: CoverageOpinion) -> str:
    """Format claim facts and coverage opinion for settlement computation."""
    return (
        f"## Settlement Computation\n"
        f"- Claimed amount: ${facts.claimed_amount}\n"
        f"- Coverage decision: {coverage.decision}\n"
        f"- Coverage confidence: {coverage.confidence}\n"
        f"- Coverage rationale: {coverage.rationale}\n\n"
        f"Compute the settlement. Apply standard deductible of $500 and "
        f"policy limit of $100,000."
    )
