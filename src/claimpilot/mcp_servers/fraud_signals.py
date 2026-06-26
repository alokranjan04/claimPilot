"""fraud-signals MCP server — score claim facts for fraud indicators.

Tools:
    score(claim_facts) → FraudScore
"""

from __future__ import annotations

from pydantic import BaseModel

from claimpilot.mcp_servers.base import AuthContext, ToolError


class FraudSignal(BaseModel):
    """A single fraud indicator with weight."""

    name: str
    weight: float
    detail: str


class FraudScore(BaseModel):
    """Aggregate fraud score with contributing signals."""

    score: float
    signals: list[FraudSignal] = []


class FraudSignalsServer:
    """In-memory fraud-signals MCP server with rule-based scoring."""

    def score(
        self,
        *,
        incident_type: str,
        claimed_amount: str,
        claimant_name: str,
        prior_claim_count: int = 0,
        flagged: bool = False,
        auth: AuthContext,
    ) -> FraudScore:
        """Score fraud risk based on claim facts and history."""
        _check_auth(auth, "fraud_signals.score")

        signals: list[FraudSignal] = []
        total = 0.0

        # Rule 1: high amount
        try:
            amt = float(claimed_amount)
        except (ValueError, TypeError):
            amt = 0.0
        if amt > 25000:
            w = 0.2
            signals.append(FraudSignal(name="high_amount", weight=w, detail=f"${amt} exceeds $25k"))
            total += w

        # Rule 2: many prior claims
        if prior_claim_count >= 3:
            w = 0.3
            signals.append(
                FraudSignal(
                    name="frequent_claimant",
                    weight=w,
                    detail=f"{prior_claim_count} prior claims",
                )
            )
            total += w

        # Rule 3: flagged claimant
        if flagged:
            w = 0.4
            signals.append(
                FraudSignal(name="flagged_claimant", weight=w, detail="Previously flagged")
            )
            total += w

        return FraudScore(score=min(total, 1.0), signals=signals)


def _check_auth(auth: AuthContext, tool: str) -> None:
    if not auth.caller:
        raise ToolError(tool, "missing caller in auth context")
