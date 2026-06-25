"""LangGraph state schema with reducer annotations.

Mirrors ``ClaimState`` from ``models/state.py`` but adds ``operator.add``
reducers on ``trace`` and ``errors`` so node returns *append* to
the lists rather than replacing them.

Note: ``from __future__ import annotations`` is intentionally omitted —
LangGraph inspects annotations at class-definition time to set up
channel reducers, so they must be live objects, not strings.
"""

import operator
from typing import Annotated, Literal, TypedDict

from claimpilot.models.claim import ClaimFacts, RawClaim
from claimpilot.models.decisions import (
    ComplianceVerdict,
    CoverageOpinion,
    PolicyContext,
    RiskAssessment,
    SettlementProposal,
)
from claimpilot.models.trace import AgentError, StepTrace


class GraphState(TypedDict, total=False):
    """LangGraph state per master-spec §5.

    ``total=False`` — most fields start empty and are populated
    incrementally.  Only ``claim_id`` and ``raw_input`` are required
    at graph entry.

    ``trace`` and ``errors`` use ``Annotated[..., operator.add]`` so
    returning ``{"trace": [item]}`` **appends** rather than replaces.
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
    trace: Annotated[list[StepTrace], operator.add]
    errors: Annotated[list[AgentError], operator.add]
