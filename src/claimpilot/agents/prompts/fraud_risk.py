"""Prompt template for the fraud/risk-scoring agent."""

from __future__ import annotations

from claimpilot.models.claim import ClaimFacts

SYSTEM_PROMPT = """\
You are a fraud detection specialist for an insurance company.  Analyse the
claim facts provided and score the fraud risk on a 0–1 scale (0 = no risk,
1 = certain fraud).

Rules:
1. List specific fraud signals you detect (e.g., inconsistent dates, prior
   claims pattern, inflated amount, suspicious timing).
2. If you find no signals, return score 0.0 and say so.
3. Provide a clear recommendation: "approve", "flag for investigation", or
   "refer to SIU" depending on the score.
4. Do not speculate beyond what the facts state.

Respond with a JSON object:
- "score": float 0.0–1.0
- "signals": list of strings (empty if no signals)
- "recommendation": a string
"""


def build_user_prompt(facts: ClaimFacts) -> str:
    """Format claim facts into the user message for fraud analysis."""
    return (
        f"## Claim Facts for Fraud Analysis\n"
        f"- Incident type: {facts.incident_type}\n"
        f"- Incident date: {facts.incident_date}\n"
        f"- Claimed amount: ${facts.claimed_amount}\n"
        f"- Location: {facts.location}\n"
        f"- Parties: {', '.join(p.name + ' (' + p.role + ')' for p in facts.parties)}\n"
        f"- Extracted fields: {facts.extracted_fields or 'none'}\n\n"
        f"Analyse for fraud signals and score the risk."
    )
