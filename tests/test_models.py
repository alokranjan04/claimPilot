"""Unit tests for Pydantic domain models and their validators."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from claimpilot.models import (
    AgentError,
    Attachment,
    Citation,
    ClaimFacts,
    ClaimState,
    ComplianceVerdict,
    CoverageOpinion,
    LineItem,
    Party,
    PolicyContext,
    RawClaim,
    RiskAssessment,
    SettlementProposal,
    StepTrace,
)

# ---------------------------------------------------------------------------
# Helpers — reusable fixtures
# ---------------------------------------------------------------------------


def _citation(**overrides: str) -> Citation:
    defaults = {"clause_id": "CL-1", "document": "policy.pdf", "snippet": "Covers fire damage."}
    return Citation(**{**defaults, **overrides})


def _party(**overrides: str) -> Party:
    defaults = {"name": "Alice", "role": "claimant"}
    return Party(**{**defaults, **overrides})


def _line_item(**overrides: object) -> LineItem:
    defaults: dict[str, object] = {"description": "Roof repair", "amount": Decimal("5000")}
    return LineItem(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# common.py
# ---------------------------------------------------------------------------


class TestAttachment:
    def test_valid(self) -> None:
        a = Attachment(filename="photo.jpg", content_type="image/jpeg", url="s3://bucket/photo.jpg")
        assert a.filename == "photo.jpg"

    def test_empty_filename_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Attachment(filename="", content_type="image/jpeg", url="s3://x")


class TestParty:
    def test_valid(self) -> None:
        p = _party()
        assert p.role == "claimant"

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Party(name="", role="claimant")


class TestCitation:
    def test_valid(self) -> None:
        c = _citation()
        assert c.clause_id == "CL-1"

    def test_empty_snippet_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Citation(clause_id="CL-1", document="doc.pdf", snippet="")


class TestLineItem:
    def test_valid(self) -> None:
        li = _line_item()
        assert li.amount == Decimal("5000")

    def test_negative_amount_allowed_for_deductibles(self) -> None:
        """Negative amounts represent deductions (e.g. deductible subtraction)."""
        item = LineItem(description="Deductible", amount=Decimal("-500"))
        assert item.amount == Decimal("-500")


# ---------------------------------------------------------------------------
# claim.py
# ---------------------------------------------------------------------------


class TestRawClaim:
    def test_valid_minimal(self) -> None:
        rc = RawClaim(claim_id="C-001", policy_number="POL-100", fnol_text="Fire in kitchen.")
        assert rc.attachments == []

    def test_with_attachments(self) -> None:
        att = Attachment(filename="photo.jpg", content_type="image/jpeg", url="s3://b/p.jpg")
        rc = RawClaim(
            claim_id="C-002",
            policy_number="POL-101",
            fnol_text="Flood.",
            attachments=[att],
        )
        assert len(rc.attachments) == 1

    def test_empty_claim_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RawClaim(claim_id="", policy_number="POL-100", fnol_text="text")


class TestClaimFacts:
    def test_valid(self) -> None:
        cf = ClaimFacts(
            incident_type="fire",
            incident_date=date(2025, 1, 15),
            claimed_amount=Decimal("10000.50"),
            location="123 Main St",
            parties=[_party()],
        )
        assert cf.claimed_amount == Decimal("10000.50")

    def test_negative_claimed_amount_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClaimFacts(
                incident_type="fire",
                incident_date=date(2025, 1, 15),
                claimed_amount=Decimal("-1"),
                location="123 Main St",
                parties=[_party()],
            )

    def test_empty_parties_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClaimFacts(
                incident_type="fire",
                incident_date=date(2025, 1, 15),
                claimed_amount=Decimal("100"),
                location="123 Main St",
                parties=[],
            )

    def test_money_is_decimal_not_float(self) -> None:
        cf = ClaimFacts(
            incident_type="fire",
            incident_date=date(2025, 1, 15),
            claimed_amount=Decimal("999.99"),
            location="Loc",
            parties=[_party()],
        )
        assert isinstance(cf.claimed_amount, Decimal)


# ---------------------------------------------------------------------------
# decisions.py
# ---------------------------------------------------------------------------


class TestPolicyContext:
    def test_valid(self) -> None:
        pc = PolicyContext(
            policy_id="POL-100",
            coverage_terms=["fire", "flood"],
            citations=[_citation()],
        )
        assert pc.exclusions == []

    def test_empty_coverage_terms_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PolicyContext(
                policy_id="POL-100",
                coverage_terms=[],
                citations=[_citation()],
            )

    def test_empty_citations_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PolicyContext(
                policy_id="POL-100",
                coverage_terms=["fire"],
                citations=[],
            )


class TestCoverageOpinion:
    def test_valid_covered(self) -> None:
        co = CoverageOpinion(
            decision="covered",
            confidence=0.95,
            rationale="Policy covers fire damage.",
            citations=[_citation()],
        )
        assert co.decision == "covered"

    def test_empty_citations_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CoverageOpinion(
                decision="denied",
                confidence=0.8,
                rationale="Not covered.",
                citations=[],
            )

    def test_confidence_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CoverageOpinion(
                decision="covered",
                confidence=-0.1,
                rationale="ok",
                citations=[_citation()],
            )

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CoverageOpinion(
                decision="covered",
                confidence=1.01,
                rationale="ok",
                citations=[_citation()],
            )

    def test_invalid_decision_literal_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CoverageOpinion(
                decision="maybe",  # type: ignore[arg-type]
                confidence=0.5,
                rationale="unsure",
                citations=[_citation()],
            )


class TestRiskAssessment:
    def test_valid(self) -> None:
        ra = RiskAssessment(score=0.3, signals=["prior_claim"], recommendation="proceed")
        assert ra.score == 0.3

    def test_score_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            RiskAssessment(score=1.5, recommendation="block")


class TestSettlementProposal:
    def test_valid(self) -> None:
        sp = SettlementProposal(
            payable_amount=Decimal("4500"),
            deductible_applied=Decimal("500"),
            limit_applied=Decimal("50000"),
            breakdown=[_line_item()],
        )
        assert sp.payable_amount == Decimal("4500")

    def test_payable_exceeds_limit_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exceeds limit_applied"):
            SettlementProposal(
                payable_amount=Decimal("60000"),
                deductible_applied=Decimal("500"),
                limit_applied=Decimal("50000"),
                breakdown=[_line_item()],
            )

    def test_negative_payable_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SettlementProposal(
                payable_amount=Decimal("-1"),
                deductible_applied=Decimal("0"),
                limit_applied=Decimal("50000"),
                breakdown=[_line_item()],
            )

    def test_empty_breakdown_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SettlementProposal(
                payable_amount=Decimal("1000"),
                deductible_applied=Decimal("0"),
                limit_applied=Decimal("50000"),
                breakdown=[],
            )

    def test_money_fields_are_decimal(self) -> None:
        sp = SettlementProposal(
            payable_amount=Decimal("1000"),
            deductible_applied=Decimal("200"),
            limit_applied=Decimal("5000"),
            breakdown=[_line_item()],
        )
        assert isinstance(sp.payable_amount, Decimal)
        assert isinstance(sp.deductible_applied, Decimal)
        assert isinstance(sp.limit_applied, Decimal)


class TestComplianceVerdict:
    def test_valid_passed(self) -> None:
        cv = ComplianceVerdict(passed=True, rationale="All checks passed.")
        assert cv.violations == []

    def test_valid_failed_with_violations(self) -> None:
        cv = ComplianceVerdict(
            passed=False,
            violations=["Missing disclosure"],
            rationale="Regulation X.1 not satisfied.",
        )
        assert len(cv.violations) == 1

    def test_failed_without_violations_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one violation"):
            ComplianceVerdict(
                passed=False,
                violations=[],
                rationale="Something failed.",
            )


# ---------------------------------------------------------------------------
# trace.py
# ---------------------------------------------------------------------------


class TestStepTrace:
    def test_defaults(self) -> None:
        st = StepTrace(node="intake")
        assert st.cost_usd == Decimal(0)
        assert st.latency_ms == 0.0
        assert isinstance(st.timestamp, datetime)
        assert st.timestamp.tzinfo == UTC

    def test_with_data(self) -> None:
        st = StepTrace(
            node="coverage_decision",
            inputs={"claim_id": "C-001"},
            outputs={"decision": "covered"},
            citations=[_citation()],
            cost_usd=Decimal("0.003"),
            latency_ms=120.5,
        )
        assert st.inputs["claim_id"] == "C-001"

    def test_negative_cost_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepTrace(node="x", cost_usd=Decimal("-1"))

    def test_negative_latency_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepTrace(node="x", latency_ms=-1.0)


class TestAgentError:
    def test_valid(self) -> None:
        ae = AgentError(node="fraud_risk", error_type="TimeoutError", message="LLM timed out")
        assert ae.recoverable is False

    def test_empty_node_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AgentError(node="", error_type="Err", message="msg")


# ---------------------------------------------------------------------------
# state.py — ClaimState is a TypedDict, so test structural compatibility
# ---------------------------------------------------------------------------


class TestClaimState:
    def test_can_construct_minimal(self) -> None:
        raw = RawClaim(claim_id="C-001", policy_number="POL-1", fnol_text="Fire.")
        state: ClaimState = {
            "claim_id": "C-001",
            "raw_input": raw,
            "trace": [],
            "errors": [],
        }
        assert state["claim_id"] == "C-001"

    def test_full_state(self) -> None:
        raw = RawClaim(claim_id="C-001", policy_number="POL-1", fnol_text="Fire.")
        state: ClaimState = {
            "claim_id": "C-001",
            "raw_input": raw,
            "facts": ClaimFacts(
                incident_type="fire",
                incident_date=date(2025, 1, 15),
                claimed_amount=Decimal("10000"),
                location="Loc",
                parties=[_party()],
            ),
            "policy_context": PolicyContext(
                policy_id="POL-1",
                coverage_terms=["fire"],
                citations=[_citation()],
            ),
            "coverage": CoverageOpinion(
                decision="covered",
                confidence=0.9,
                rationale="Covered.",
                citations=[_citation()],
            ),
            "risk": RiskAssessment(score=0.1, recommendation="proceed"),
            "settlement": SettlementProposal(
                payable_amount=Decimal("9500"),
                deductible_applied=Decimal("500"),
                limit_applied=Decimal("50000"),
                breakdown=[_line_item()],
            ),
            "compliance": ComplianceVerdict(passed=True, rationale="OK"),
            "disposition": "auto_approved",
            "trace": [StepTrace(node="intake")],
            "errors": [],
        }
        assert state["disposition"] == "auto_approved"
        assert len(state["trace"]) == 1


# ---------------------------------------------------------------------------
# Re-export smoke test — every public name importable from claimpilot.models
# ---------------------------------------------------------------------------


class TestReExports:
    def test_all_models_importable(self) -> None:
        from claimpilot.models import __all__

        assert len(__all__) == 14  # noqa: PLR2004
