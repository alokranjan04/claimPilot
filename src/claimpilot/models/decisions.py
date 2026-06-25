"""Models representing agent decision outputs."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from claimpilot.models.common import Citation, LineItem


class PolicyContext(BaseModel):
    """Relevant policy clauses and coverage terms retrieved by the Policy-RAG agent."""

    policy_id: str = Field(min_length=1)
    coverage_terms: list[str] = Field(min_length=1)
    exclusions: list[str] = []
    citations: list[Citation] = Field(min_length=1)


class CoverageOpinion(BaseModel):
    """The Coverage agent's determination on whether the claim is covered."""

    decision: Literal["covered", "denied", "partial"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)

    @model_validator(mode="after")
    def _citations_required(self) -> "CoverageOpinion":
        """A coverage decision must always cite at least one policy clause."""
        if not self.citations:
            msg = "CoverageOpinion requires at least one citation."
            raise ValueError(msg)
        return self


class RiskAssessment(BaseModel):
    """Fraud/risk scoring produced by the Fraud-Risk agent."""

    score: float = Field(ge=0.0, le=1.0, description="0 = no risk, 1 = certain fraud")
    signals: list[str] = []
    recommendation: str = Field(min_length=1)


class SettlementProposal(BaseModel):
    """Computed settlement produced by the Settlement agent."""

    payable_amount: Decimal = Field(ge=Decimal(0))
    deductible_applied: Decimal = Field(ge=Decimal(0))
    limit_applied: Decimal = Field(ge=Decimal(0))
    breakdown: list[LineItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _payable_within_limit(self) -> "SettlementProposal":
        """Payable amount must not exceed the policy limit."""
        if self.payable_amount > self.limit_applied:
            msg = (
                f"payable_amount ({self.payable_amount}) "
                f"exceeds limit_applied ({self.limit_applied})."
            )
            raise ValueError(msg)
        return self


class ComplianceVerdict(BaseModel):
    """Result of the Compliance/Audit agent's review."""

    passed: bool
    violations: list[str] = []
    rationale: str = Field(min_length=1)
    citations: list[Citation] = []

    @model_validator(mode="after")
    def _violations_match_passed(self) -> "ComplianceVerdict":
        """If compliance failed there must be at least one violation listed."""
        if not self.passed and not self.violations:
            msg = "A failed ComplianceVerdict must list at least one violation."
            raise ValueError(msg)
        return self
