"""Fraud/risk agent unit tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from claimpilot.agents.fraud_risk import FraudRiskAgentError, assess
from claimpilot.infra.providers.fakes import FakeLLMClient
from claimpilot.models.claim import ClaimFacts
from claimpilot.models.common import Party


def _facts() -> ClaimFacts:
    return ClaimFacts(
        incident_type="auto_collision",
        incident_date=date(2026, 6, 1),
        claimed_amount=Decimal("5000"),
        location="Springfield, IL",
        parties=[Party(name="Jane Doe", role="claimant")],
    )


class TestFraudRiskHappyPath:
    async def test_low_risk(self) -> None:
        llm = FakeLLMClient(
            scripted=[
                {
                    "score": 0.05,
                    "signals": [],
                    "recommendation": "approve",
                }
            ]
        )
        result = await assess(_facts(), llm=llm)
        assert result.score == pytest.approx(0.05)
        assert result.signals == []
        assert "approve" in result.recommendation.lower()

    async def test_high_risk_with_signals(self) -> None:
        llm = FakeLLMClient(
            scripted=[
                {
                    "score": 0.85,
                    "signals": ["inflated amount", "suspicious timing"],
                    "recommendation": "refer to SIU",
                }
            ]
        )
        result = await assess(_facts(), llm=llm)
        assert result.score == pytest.approx(0.85)
        assert len(result.signals) == 2
        assert "SIU" in result.recommendation


class TestFraudRiskEdgeCases:
    async def test_score_clamped(self) -> None:
        llm = FakeLLMClient(
            scripted=[
                {
                    "score": 1.5,
                    "signals": [],
                    "recommendation": "clamp test",
                }
            ]
        )
        result = await assess(_facts(), llm=llm)
        assert result.score <= 1.0

    async def test_missing_signals_defaults_empty(self) -> None:
        llm = FakeLLMClient(
            scripted=[
                {
                    "score": 0.1,
                    "recommendation": "ok",
                }
            ]
        )
        result = await assess(_facts(), llm=llm)
        assert result.signals == []


class TestFraudRiskError:
    async def test_malformed_raises(self) -> None:
        llm = FakeLLMClient(scripted=["not json {"])
        with pytest.raises(FraudRiskAgentError) as exc_info:
            await assess(_facts(), llm=llm)
        assert exc_info.value.error.node == "fraud_risk"
