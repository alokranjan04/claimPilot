"""Prompt template for the compliance/audit agent."""

from __future__ import annotations

from claimpilot.models.claim import ClaimFacts
from claimpilot.models.decisions import CoverageOpinion, PolicyContext, SettlementProposal

SYSTEM_PROMPT = """\
You are a regulatory compliance officer reviewing an insurance claim
adjudication.  Verify that the process and decision comply with applicable
regulations and internal policy.

Rules:
1. Check that the claim was processed within regulatory time limits.
2. Verify the settlement is based on actual cash value or replacement cost
   as defined in the policy.
3. Flag any violations of fair settlement practices.
4. If compliant, say so clearly.  If not, list each violation.

Respond with a JSON object:
- "passed": boolean
- "violations": list of strings (empty if passed)
- "rationale": a string explaining your assessment
- "citations": list of {"clause_id": str, "document": str, "snippet": str}
  (may be empty if no regulatory clauses were consulted)
"""


def build_user_prompt(
    facts: ClaimFacts,
    context: PolicyContext,
    coverage: CoverageOpinion,
    settlement: SettlementProposal,
) -> str:
    """Format the full adjudication record for compliance review."""
    return (
        f"## Compliance Review\n"
        f"- Incident type: {facts.incident_type}\n"
        f"- Claimed amount: ${facts.claimed_amount}\n"
        f"- Coverage decision: {coverage.decision} (confidence: {coverage.confidence})\n"
        f"- Settlement payable: ${settlement.payable_amount}\n"
        f"- Deductible applied: ${settlement.deductible_applied}\n"
        f"- Policy limit: ${settlement.limit_applied}\n"
        f"- Policy ID: {context.policy_id}\n\n"
        f"Verify compliance with regulations and internal policy."
    )
