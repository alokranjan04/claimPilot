"""LangGraph state schema — the single typed object threaded through the graph."""

from typing import Literal, TypedDict

from claimpilot.models.claim import ClaimFacts, RawClaim
from claimpilot.models.decisions import (
    ComplianceVerdict,
    CoverageOpinion,
    PolicyContext,
    RiskAssessment,
    SettlementProposal,
)
from claimpilot.models.trace import AgentError, StepTrace


class ClaimState(TypedDict, total=False):
    """Graph state per master-spec §5.

    ``total=False`` because most fields start as ``None`` / empty and are
    populated incrementally as the claim flows through the graph.  The only
    required key at graph entry is ``claim_id`` + ``raw_input``.
    """

    claim_id: str
    raw_input: RawClaim
    facts: ClaimFacts | None
    policy_context: PolicyContext | None
    coverage: CoverageOpinion | None
    risk: RiskAssessment | None
    settlement: SettlementProposal | None
    compliance: ComplianceVerdict | None
    disposition: Literal["auto_approved", "auto_denied", "escalated"] | None
    trace: list[StepTrace]
    errors: list[AgentError]
