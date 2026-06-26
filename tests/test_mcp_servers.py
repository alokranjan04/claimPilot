"""MCP tool server tests — typed schemas, validation, authz, correctness."""

from __future__ import annotations

import pytest

from claimpilot.mcp_servers.base import AuthContext, ToolError
from claimpilot.mcp_servers.claims_history import ClaimsHistoryServer
from claimpilot.mcp_servers.fraud_signals import FraudSignalsServer
from claimpilot.mcp_servers.policy_db import PolicyDbServer
from claimpilot.mcp_servers.regs import RegsServer

_AUTH = AuthContext(caller="test", scopes=["read"])
_BAD_AUTH = AuthContext(caller="", scopes=[])


# ── policy_db ────────────────────────────────────────────────────────────


class TestPolicyDb:
    def test_search_finds_match(self) -> None:
        srv = PolicyDbServer()
        hits = srv.search("comprehensive", auth=_AUTH)
        assert len(hits) >= 1
        assert any("§1.1" in h.clause_id for h in hits)

    def test_search_no_match(self) -> None:
        srv = PolicyDbServer()
        hits = srv.search("quantum physics", auth=_AUTH)
        assert hits == []

    def test_search_filter_by_policy_id(self) -> None:
        srv = PolicyDbServer()
        hits = srv.search("coverage", policy_id="§1", auth=_AUTH)
        assert all(h.clause_id.startswith("§1") for h in hits)

    def test_get_clause(self) -> None:
        srv = PolicyDbServer()
        clause = srv.get_clause("§1.1", auth=_AUTH)
        assert clause is not None
        assert clause.clause_id == "§1.1"

    def test_get_clause_missing(self) -> None:
        srv = PolicyDbServer()
        assert srv.get_clause("§99.99", auth=_AUTH) is None

    def test_empty_query_raises(self) -> None:
        srv = PolicyDbServer()
        with pytest.raises(ToolError, match="query"):
            srv.search("", auth=_AUTH)

    def test_missing_auth_raises(self) -> None:
        srv = PolicyDbServer()
        with pytest.raises(ToolError, match="caller"):
            srv.search("test", auth=_BAD_AUTH)


# ── claims_history ───────────────────────────────────────────────────────


class TestClaimsHistory:
    def test_lookup_found(self) -> None:
        srv = ClaimsHistoryServer()
        record = srv.lookup("CLT-001", auth=_AUTH)
        assert record is not None
        assert record.name == "Jane Doe"

    def test_lookup_missing(self) -> None:
        srv = ClaimsHistoryServer()
        assert srv.lookup("CLT-UNKNOWN", auth=_AUTH) is None

    def test_prior_claims(self) -> None:
        srv = ClaimsHistoryServer()
        claims = srv.prior_claims("POL-100", auth=_AUTH)
        assert len(claims) >= 1
        assert all(c.policy_id == "POL-100" for c in claims)

    def test_prior_claims_empty(self) -> None:
        srv = ClaimsHistoryServer()
        assert srv.prior_claims("POL-UNKNOWN", auth=_AUTH) == []

    def test_empty_id_raises(self) -> None:
        srv = ClaimsHistoryServer()
        with pytest.raises(ToolError, match="claimant_id"):
            srv.lookup("", auth=_AUTH)

    def test_missing_auth_raises(self) -> None:
        srv = ClaimsHistoryServer()
        with pytest.raises(ToolError, match="caller"):
            srv.lookup("CLT-001", auth=_BAD_AUTH)


# ── fraud_signals ────────────────────────────────────────────────────────


class TestFraudSignals:
    def test_clean_claim_low_score(self) -> None:
        srv = FraudSignalsServer()
        result = srv.score(
            incident_type="auto_collision",
            claimed_amount="5000",
            claimant_name="Jane",
            auth=_AUTH,
        )
        assert result.score == 0.0
        assert result.signals == []

    def test_high_amount_signal(self) -> None:
        srv = FraudSignalsServer()
        result = srv.score(
            incident_type="auto_collision",
            claimed_amount="50000",
            claimant_name="Jane",
            auth=_AUTH,
        )
        assert result.score > 0
        assert any(s.name == "high_amount" for s in result.signals)

    def test_flagged_claimant(self) -> None:
        srv = FraudSignalsServer()
        result = srv.score(
            incident_type="theft",
            claimed_amount="5000",
            claimant_name="Sam",
            flagged=True,
            prior_claim_count=5,
            auth=_AUTH,
        )
        assert result.score >= 0.7
        signal_names = {s.name for s in result.signals}
        assert "flagged_claimant" in signal_names
        assert "frequent_claimant" in signal_names

    def test_score_capped_at_1(self) -> None:
        srv = FraudSignalsServer()
        result = srv.score(
            incident_type="theft",
            claimed_amount="100000",
            claimant_name="Sam",
            flagged=True,
            prior_claim_count=10,
            auth=_AUTH,
        )
        assert result.score <= 1.0

    def test_missing_auth_raises(self) -> None:
        srv = FraudSignalsServer()
        with pytest.raises(ToolError, match="caller"):
            srv.score(
                incident_type="auto",
                claimed_amount="1000",
                claimant_name="x",
                auth=_BAD_AUTH,
            )


# ── regs ─────────────────────────────────────────────────────────────────


class TestRegs:
    def test_search_finds_match(self) -> None:
        srv = RegsServer()
        hits = srv.search("IL", "settlement", auth=_AUTH)
        assert len(hits) >= 1
        assert any("§R.2" in h.reg_id for h in hits)

    def test_search_no_match(self) -> None:
        srv = RegsServer()
        hits = srv.search("IL", "quantum", auth=_AUTH)
        assert hits == []

    def test_search_wrong_jurisdiction(self) -> None:
        srv = RegsServer()
        hits = srv.search("CA", "settlement", auth=_AUTH)
        assert hits == []

    def test_empty_jurisdiction_raises(self) -> None:
        srv = RegsServer()
        with pytest.raises(ToolError, match="jurisdiction"):
            srv.search("", "topic", auth=_AUTH)

    def test_empty_topic_raises(self) -> None:
        srv = RegsServer()
        with pytest.raises(ToolError, match="topic"):
            srv.search("IL", "", auth=_AUTH)

    def test_missing_auth_raises(self) -> None:
        srv = RegsServer()
        with pytest.raises(ToolError, match="caller"):
            srv.search("IL", "fraud", auth=_BAD_AUTH)
