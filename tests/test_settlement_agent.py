"""Settlement agent unit tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from claimpilot.agents.settlement import SettlementAgentError, compute
from claimpilot.infra.providers.fakes import FakeLLMClient
from claimpilot.models.claim import ClaimFacts
from claimpilot.models.common import Citation, Party
from claimpilot.models.decisions import CoverageOpinion

_CITE = Citation(clause_id="§1.1", document="Auto Policy", snippet="Comprehensive.")


def _facts(amount: str = "5000") -> ClaimFacts:
    return ClaimFacts(
        incident_type="auto_collision",
        incident_date=date(2026, 6, 1),
        claimed_amount=Decimal(amount),
        location="Springfield, IL",
        parties=[Party(name="Jane Doe", role="claimant")],
    )


def _coverage(decision: str = "covered") -> CoverageOpinion:
    return CoverageOpinion(
        decision=decision,
        confidence=0.9,
        rationale="Covered under §1.1.",
        citations=[_CITE],
    )


class TestSettlementHappyPath:
    async def test_covered_settlement(self) -> None:
        llm = FakeLLMClient(
            scripted=[
                {
                    "payable_amount": "4500.00",
                    "deductible_applied": "500.00",
                    "limit_applied": "100000.00",
                    "breakdown": [
                        {"description": "Repair costs", "amount": "4500.00"},
                    ],
                }
            ]
        )
        result = await compute(_facts(), _coverage(), llm=llm)
        assert result.payable_amount == Decimal("4500.00")
        assert result.deductible_applied == Decimal("500.00")
        assert len(result.breakdown) >= 1

    async def test_denied_no_llm_call(self) -> None:
        """Denied coverage → zero settlement without calling LLM."""
        llm = FakeLLMClient()
        result = await compute(_facts(), _coverage("denied"), llm=llm)
        assert result.payable_amount == Decimal(0)
        assert llm._call_count == 0  # noqa: SLF001


class TestSettlementEdgeCases:
    async def test_payable_clamped_to_limit(self) -> None:
        """If LLM returns payable > limit, it's clamped."""
        llm = FakeLLMClient(
            scripted=[
                {
                    "payable_amount": "200000.00",
                    "deductible_applied": "0",
                    "limit_applied": "100000.00",
                    "breakdown": [{"description": "Repair", "amount": "200000.00"}],
                }
            ]
        )
        result = await compute(_facts(), _coverage(), llm=llm)
        assert result.payable_amount <= result.limit_applied

    async def test_empty_breakdown_gets_default(self) -> None:
        llm = FakeLLMClient(
            scripted=[
                {
                    "payable_amount": "3000",
                    "deductible_applied": "500",
                    "limit_applied": "100000",
                    "breakdown": [],
                }
            ]
        )
        result = await compute(_facts(), _coverage(), llm=llm)
        assert len(result.breakdown) >= 1


class TestSettlementError:
    async def test_malformed_raises(self) -> None:
        llm = FakeLLMClient(scripted=["[bad]"])
        with pytest.raises(SettlementAgentError) as exc_info:
            await compute(_facts(), _coverage(), llm=llm)
        assert exc_info.value.error.node == "settlement"
