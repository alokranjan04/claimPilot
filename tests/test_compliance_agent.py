"""Compliance agent unit tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from claimpilot.agents.compliance import ComplianceAgentError, review
from claimpilot.infra.providers.fakes import FakeLLMClient
from claimpilot.models.claim import ClaimFacts
from claimpilot.models.common import Citation, LineItem, Party
from claimpilot.models.decisions import (
    CoverageOpinion,
    PolicyContext,
    SettlementProposal,
)

_CITE = Citation(clause_id="§1.1", document="Auto Policy", snippet="Comprehensive.")


def _facts() -> ClaimFacts:
    return ClaimFacts(
        incident_type="auto_collision",
        incident_date=date(2026, 6, 1),
        claimed_amount=Decimal("5000"),
        location="Springfield, IL",
        parties=[Party(name="Jane Doe", role="claimant")],
    )


def _context() -> PolicyContext:
    return PolicyContext(
        policy_id="POL-100",
        coverage_terms=["comprehensive coverage"],
        citations=[_CITE],
    )


def _coverage() -> CoverageOpinion:
    return CoverageOpinion(
        decision="covered",
        confidence=0.9,
        rationale="Covered under §1.1.",
        citations=[_CITE],
    )


def _settlement() -> SettlementProposal:
    return SettlementProposal(
        payable_amount=Decimal("4500"),
        deductible_applied=Decimal("500"),
        limit_applied=Decimal("100000"),
        breakdown=[LineItem(description="Repair costs", amount=Decimal("4500"))],
    )


class TestComplianceHappyPath:
    async def test_passed(self) -> None:
        llm = FakeLLMClient(
            scripted=[
                {
                    "passed": True,
                    "violations": [],
                    "rationale": "All regulatory requirements met.",
                    "citations": [],
                }
            ]
        )
        result = await review(_facts(), _context(), _coverage(), _settlement(), llm=llm)
        assert result.passed is True
        assert result.violations == []

    async def test_failed_with_violations(self) -> None:
        llm = FakeLLMClient(
            scripted=[
                {
                    "passed": False,
                    "violations": ["Settlement below ACV", "Late processing"],
                    "rationale": "Two regulatory violations found.",
                    "citations": [],
                }
            ]
        )
        result = await review(_facts(), _context(), _coverage(), _settlement(), llm=llm)
        assert result.passed is False
        assert len(result.violations) == 2


class TestComplianceEdgeCases:
    async def test_failed_no_violations_gets_default(self) -> None:
        """ComplianceVerdict validator requires violations when failed.
        Agent synthesises one if the LLM omits them."""
        llm = FakeLLMClient(
            scripted=[
                {
                    "passed": False,
                    "violations": [],
                    "rationale": "Issues found.",
                }
            ]
        )
        result = await review(_facts(), _context(), _coverage(), _settlement(), llm=llm)
        assert result.passed is False
        assert len(result.violations) >= 1

    async def test_citations_parsed(self) -> None:
        llm = FakeLLMClient(
            scripted=[
                {
                    "passed": True,
                    "violations": [],
                    "rationale": "Compliant per §R.1.",
                    "citations": [{"clause_id": "§R.1", "document": "Reg", "snippet": "Timely."}],
                }
            ]
        )
        result = await review(_facts(), _context(), _coverage(), _settlement(), llm=llm)
        assert len(result.citations) == 1
        assert result.citations[0].clause_id == "§R.1"


class TestComplianceError:
    async def test_malformed_raises(self) -> None:
        llm = FakeLLMClient(scripted=["not json"])
        with pytest.raises(ComplianceAgentError) as exc_info:
            await review(_facts(), _context(), _coverage(), _settlement(), llm=llm)
        assert exc_info.value.error.node == "compliance"
