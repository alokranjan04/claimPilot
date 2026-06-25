"""Coverage-decision agent acceptance tests — spec 20.

All seven acceptance criteria from ``docs/specs/20-agent-coverage.md``.
Uses the fake LLM with scripted responses; no network, no API keys.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from claimpilot.agents.coverage import CoverageAgentError, decide
from claimpilot.infra.providers.fakes import FakeLLMClient
from claimpilot.models.claim import ClaimFacts
from claimpilot.models.common import Citation, Party
from claimpilot.models.decisions import PolicyContext

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_CITE_COVERAGE = Citation(
    clause_id="§1.1",
    document="Standard Auto Policy",
    snippet="Comprehensive coverage: collisions, theft, vandalism, weather.",
)
_CITE_EXCLUSION = Citation(
    clause_id="§1.3",
    document="Standard Auto Policy",
    snippet="Excludes intentional damage, racing, commercial use.",
)
_CITE_LIABILITY = Citation(
    clause_id="§1.2",
    document="Standard Auto Policy",
    snippet="Liability coverage: bodily injury and property damage.",
)


def _make_facts() -> ClaimFacts:
    return ClaimFacts(
        incident_type="auto_collision",
        incident_date=date(2026, 6, 1),
        claimed_amount=Decimal("5000"),
        location="Springfield, IL",
        parties=[Party(name="Jane Doe", role="claimant")],
    )


def _make_context(
    *,
    citations: list[Citation] | None = None,
    coverage_terms: list[str] | None = None,
    exclusions: list[str] | None = None,
    sufficient: bool = True,
) -> PolicyContext:
    return PolicyContext(
        policy_id="POL-100",
        coverage_terms=coverage_terms or ["comprehensive coverage"],
        exclusions=exclusions or [],
        citations=citations or [_CITE_COVERAGE, _CITE_LIABILITY],
        sufficient=sufficient,
    )


# ── 1. Covered case ──────────────────────────────────────────────────────


class TestCoveredCase:
    async def test_covered_decision(self) -> None:
        """Matching coverage clause → covered, citations subset of context."""
        llm = FakeLLMClient(
            scripted=[
                {
                    "decision": "covered",
                    "confidence": 0.95,
                    "rationale": "Claim is a collision covered under §1.1 comprehensive.",
                    "citations": [_CITE_COVERAGE.model_dump()],
                }
            ]
        )
        ctx = _make_context(citations=[_CITE_COVERAGE, _CITE_LIABILITY])
        result = await decide(_make_facts(), ctx, llm=llm)

        assert result.decision == "covered"
        assert result.confidence >= 0.8
        assert len(result.citations) >= 1
        assert all(c.clause_id in {"§1.1", "§1.2"} for c in result.citations)


# ── 2. Denied case ───────────────────────────────────────────────────────


class TestDeniedCase:
    async def test_denied_exclusion_cited(self) -> None:
        """Exclusion clause → denied, exclusion clause_id cited."""
        llm = FakeLLMClient(
            scripted=[
                {
                    "decision": "denied",
                    "confidence": 0.9,
                    "rationale": "Intentional damage excluded under §1.3.",
                    "citations": [_CITE_EXCLUSION.model_dump()],
                }
            ]
        )
        ctx = _make_context(
            citations=[_CITE_EXCLUSION],
            coverage_terms=["exclusions"],
            exclusions=["intentional damage"],
        )
        result = await decide(_make_facts(), ctx, llm=llm)

        assert result.decision == "denied"
        assert any(c.clause_id == "§1.3" for c in result.citations)


# ── 3. Partial / conflict ────────────────────────────────────────────────


class TestPartialConflict:
    async def test_partial_both_cited(self) -> None:
        """Covering + excluding clauses → partial, both cited."""
        llm = FakeLLMClient(
            scripted=[
                {
                    "decision": "partial",
                    "confidence": 0.7,
                    "rationale": "§1.1 covers collision but §1.3 excludes racing-related damage.",
                    "citations": [
                        _CITE_COVERAGE.model_dump(),
                        _CITE_EXCLUSION.model_dump(),
                    ],
                }
            ]
        )
        ctx = _make_context(
            citations=[_CITE_COVERAGE, _CITE_EXCLUSION],
            coverage_terms=["comprehensive coverage", "exclusions"],
            exclusions=["racing"],
        )
        result = await decide(_make_facts(), ctx, llm=llm)

        assert result.decision == "partial"
        cited_ids = {c.clause_id for c in result.citations}
        assert "§1.1" in cited_ids
        assert "§1.3" in cited_ids


# ── 4. Insufficient context — LLM not called ────────────────────────────


class TestInsufficientContext:
    async def test_no_llm_call_low_confidence(self) -> None:
        """sufficient=False → immediate return, LLM never invoked."""
        llm = FakeLLMClient()
        ctx = _make_context(sufficient=False)

        result = await decide(_make_facts(), ctx, llm=llm)

        assert result.decision == "partial"
        assert result.confidence <= 0.2
        assert "insufficient" in result.rationale.lower()
        # Assert the LLM was NOT called.
        assert llm._call_count == 0  # noqa: SLF001


# ── 5. Hallucinated citation stripped ────────────────────────────────────


class TestHallucinatedCitation:
    async def test_hallucinated_stripped_valid_kept(self) -> None:
        """A citation whose clause_id is absent from context is removed;
        valid citations are retained."""
        llm = FakeLLMClient(
            scripted=[
                {
                    "decision": "covered",
                    "confidence": 0.9,
                    "rationale": "Covered under §1.1; also see §99.9.",
                    "citations": [
                        _CITE_COVERAGE.model_dump(),
                        {"clause_id": "§99.9", "document": "Fake", "snippet": "Hallucinated"},
                    ],
                }
            ]
        )
        ctx = _make_context(citations=[_CITE_COVERAGE, _CITE_LIABILITY])
        result = await decide(_make_facts(), ctx, llm=llm)

        cited_ids = {c.clause_id for c in result.citations}
        assert "§1.1" in cited_ids
        assert "§99.9" not in cited_ids

    async def test_all_hallucinated_triggers_escalation(self) -> None:
        """If every citation is hallucinated → low-confidence escalation."""
        llm = FakeLLMClient(
            scripted=[
                {
                    "decision": "covered",
                    "confidence": 0.95,
                    "rationale": "Covered under fictional clauses.",
                    "citations": [
                        {"clause_id": "§99.9", "document": "Fake", "snippet": "Hallucinated"},
                    ],
                }
            ]
        )
        ctx = _make_context(citations=[_CITE_COVERAGE])
        result = await decide(_make_facts(), ctx, llm=llm)

        assert result.decision == "partial"
        assert result.confidence <= 0.2
        assert "invalid" in result.rationale.lower()


# ── 6. Confidence cap on weak retrieval ──────────────────────────────────


class TestConfidenceCap:
    async def test_weak_retrieval_caps_confidence(self) -> None:
        """With only 1 citation in context (weak retrieval), confidence
        is capped at 0.6 regardless of model assertiveness."""
        llm = FakeLLMClient(
            scripted=[
                {
                    "decision": "covered",
                    "confidence": 0.99,
                    "rationale": "Very confident.",
                    "citations": [_CITE_COVERAGE.model_dump()],
                }
            ]
        )
        ctx = _make_context(citations=[_CITE_COVERAGE])  # only 1 citation
        result = await decide(_make_facts(), ctx, llm=llm)

        assert result.confidence <= 0.6

    async def test_strong_retrieval_no_cap(self) -> None:
        """With 2+ citations (strong retrieval), confidence is not capped."""
        llm = FakeLLMClient(
            scripted=[
                {
                    "decision": "covered",
                    "confidence": 0.95,
                    "rationale": "Well-supported decision.",
                    "citations": [
                        _CITE_COVERAGE.model_dump(),
                        _CITE_LIABILITY.model_dump(),
                    ],
                }
            ]
        )
        ctx = _make_context(citations=[_CITE_COVERAGE, _CITE_LIABILITY])
        result = await decide(_make_facts(), ctx, llm=llm)

        assert result.confidence == 0.95


# ── 7. AgentError on malformed output ────────────────────────────────────


class TestAgentError:
    async def test_malformed_json_raises(self) -> None:
        """Non-JSON LLM output → CoverageAgentError with AgentError payload."""
        llm = FakeLLMClient(scripted=["this is not json {{{"])
        ctx = _make_context()

        with pytest.raises(CoverageAgentError) as exc_info:
            await decide(_make_facts(), ctx, llm=llm)

        assert exc_info.value.error.node == "coverage_decision"
        assert exc_info.value.error.error_type == "MalformedOutput"

    async def test_non_dict_json_raises(self) -> None:
        """JSON array instead of object → CoverageAgentError."""
        llm = FakeLLMClient(scripted=["[1, 2, 3]"])
        ctx = _make_context()

        with pytest.raises(CoverageAgentError) as exc_info:
            await decide(_make_facts(), ctx, llm=llm)

        assert "MalformedOutput" in exc_info.value.error.error_type


# ── 8. No concrete provider imports ──────────────────────────────────────
# (Enforced by make check: mypy strict + ruff clean.)
