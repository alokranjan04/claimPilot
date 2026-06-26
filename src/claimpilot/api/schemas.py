"""FastAPI request / response schemas for the ClaimPilot API.

All money amounts use ``Decimal`` (serialised as strings in JSON by Pydantic v2),
never ``float``, per master-spec §8 / CLAUDE.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from claimpilot.models.claim import ClaimFacts
from claimpilot.models.decisions import (
    ComplianceVerdict,
    CoverageOpinion,
    PolicyContext,
    RiskAssessment,
    SettlementProposal,
)
from claimpilot.models.trace import AgentError, StepTrace
from claimpilot.observability.cost_meter import ClaimCostSummary

# ---------------------------------------------------------------------------
# POST /v1/claims
# ---------------------------------------------------------------------------


class SubmitClaimRequest(BaseModel):
    """Body for submitting a new claim."""

    policy_number: str = Field(min_length=1)
    fnol_text: str = Field(min_length=1, description="First Notice of Loss narrative text.")


class SubmitClaimResponse(BaseModel):
    """Immediate response: claim accepted for async processing."""

    claim_id: str
    status: str = "pending"


# ---------------------------------------------------------------------------
# GET /v1/claims/{id}
# ---------------------------------------------------------------------------


class ClaimStatusResponse(BaseModel):
    """Full claim status including all agent outputs and trace."""

    claim_id: str
    status: Literal["pending", "processing", "completed", "escalated", "error"]
    disposition: str | None = None

    # Agent outputs (None until the relevant node has run)
    facts: ClaimFacts | None = None
    policy_context: PolicyContext | None = None
    coverage: CoverageOpinion | None = None
    risk: RiskAssessment | None = None
    settlement: SettlementProposal | None = None  # Decimal amounts → string in JSON
    compliance: ComplianceVerdict | None = None

    # Audit trail
    trace: list[StepTrace] = Field(default_factory=list)
    errors: list[AgentError] = Field(default_factory=list)

    # M9: per-claim cost and latency summary
    cost_summary: ClaimCostSummary | None = None

    # Human-in-the-loop
    human_decision: str | None = None
    human_notes: str | None = None

    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# POST /v1/claims/{id}/decision
# ---------------------------------------------------------------------------


class HumanDecisionRequest(BaseModel):
    """Human adjudicator's decision on an escalated claim."""

    decision: Literal["approve", "deny"]
    notes: str | None = None


class HumanDecisionResponse(BaseModel):
    """Confirmation of the recorded human decision."""

    claim_id: str
    status: str
    disposition: str
    human_decision: str


# ---------------------------------------------------------------------------
# GET /v1/evals/latest  (thin wrapper over evals.metrics.Scorecard)
# ---------------------------------------------------------------------------


class EvalScorecard(BaseModel):
    """Subset of the eval scorecard returned by the API."""

    total_cases: int
    passed: int
    failed: int
    decision_accuracy: float
    escalation_precision: float
    escalation_recall: float
    citation_faithfulness: float
    tool_call_accuracy: float
    p50_latency_ms: float
    p95_latency_ms: float
    gate_passed: bool
    gate_failures: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
