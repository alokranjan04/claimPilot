"""claims-history MCP server — lookup and prior_claims over synthetic history.

Tools:
    lookup(claimant_id)    → ClaimantRecord | None
    prior_claims(policy_id) → list[PriorClaim]
"""

from __future__ import annotations

from pydantic import BaseModel

from claimpilot.mcp_servers.base import AuthContext, ToolError


class PriorClaim(BaseModel):
    """A historical claim record."""

    claim_id: str
    policy_id: str
    incident_type: str
    amount: str
    date: str
    disposition: str


class ClaimantRecord(BaseModel):
    """Profile of a claimant with their history."""

    claimant_id: str
    name: str
    total_claims: int = 0
    flagged: bool = False
    prior_claims: list[PriorClaim] = []


class ClaimsHistoryServer:
    """In-memory claims-history MCP server backed by fixture data."""

    def __init__(self, records: dict[str, ClaimantRecord] | None = None) -> None:
        self._records: dict[str, ClaimantRecord] = records or _default_records()

    def lookup(
        self,
        claimant_id: str,
        *,
        auth: AuthContext,
    ) -> ClaimantRecord | None:
        """Look up a claimant by ID."""
        _check_auth(auth, "claims_history.lookup")
        if not claimant_id:
            raise ToolError("claims_history.lookup", "claimant_id must not be empty")
        return self._records.get(claimant_id)

    def prior_claims(
        self,
        policy_id: str,
        *,
        auth: AuthContext,
    ) -> list[PriorClaim]:
        """Get all prior claims for a policy."""
        _check_auth(auth, "claims_history.prior_claims")
        if not policy_id:
            raise ToolError("claims_history.prior_claims", "policy_id must not be empty")
        results: list[PriorClaim] = []
        for record in self._records.values():
            for claim in record.prior_claims:
                if claim.policy_id == policy_id:
                    results.append(claim)
        return results


def _check_auth(auth: AuthContext, tool: str) -> None:
    if not auth.caller:
        raise ToolError(tool, "missing caller in auth context")


def _default_records() -> dict[str, ClaimantRecord]:
    return {
        "CLT-001": ClaimantRecord(
            claimant_id="CLT-001",
            name="Jane Doe",
            total_claims=2,
            flagged=False,
            prior_claims=[
                PriorClaim(
                    claim_id="CLM-OLD-1",
                    policy_id="POL-100",
                    incident_type="auto_collision",
                    amount="3000",
                    date="2025-01-15",
                    disposition="auto_approved",
                ),
            ],
        ),
        "CLT-002": ClaimantRecord(
            claimant_id="CLT-002",
            name="Suspicious Sam",
            total_claims=5,
            flagged=True,
            prior_claims=[
                PriorClaim(
                    claim_id="CLM-OLD-2",
                    policy_id="POL-200",
                    incident_type="auto_collision",
                    amount="9000",
                    date="2025-06-01",
                    disposition="escalated",
                ),
                PriorClaim(
                    claim_id="CLM-OLD-3",
                    policy_id="POL-200",
                    incident_type="theft",
                    amount="15000",
                    date="2025-09-10",
                    disposition="escalated",
                ),
            ],
        ),
    }
