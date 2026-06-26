"""Compliance/audit agent.

Pure async function with optional MCP tool enrichment via the regs server.
"""

from __future__ import annotations

import json
from typing import Any

from claimpilot.agents.prompts.compliance import SYSTEM_PROMPT, build_user_prompt
from claimpilot.infra.interfaces import LLMClient
from claimpilot.mcp_servers.base import AuthContext
from claimpilot.mcp_servers.regs import RegsServer
from claimpilot.models.claim import ClaimFacts
from claimpilot.models.common import Citation
from claimpilot.models.decisions import (
    ComplianceVerdict,
    CoverageOpinion,
    PolicyContext,
    SettlementProposal,
)
from claimpilot.models.trace import AgentError

_AUTH = AuthContext(caller="compliance_agent", scopes=["regs.read"])


class ComplianceAgentError(Exception):
    """Raised by the compliance agent on irrecoverable error."""

    def __init__(self, error: AgentError) -> None:
        self.error = error
        super().__init__(error.message)


async def review(
    facts: ClaimFacts,
    context: PolicyContext,
    coverage: CoverageOpinion,
    settlement: SettlementProposal,
    *,
    llm: LLMClient,
    regs: RegsServer | None = None,
) -> ComplianceVerdict:
    """Review the adjudication for regulatory/policy compliance.

    When *regs* is provided, searches for applicable regulations and
    includes them in the LLM prompt.
    """
    tool_context = ""

    # ── MCP tool call: regulatory search ─────────────────────────────
    if regs is not None:
        jurisdiction = context.citations[0].document if context.citations else "IL"
        hits = regs.search(jurisdiction, "settlement", auth=_AUTH)
        hits += regs.search(jurisdiction, "claims", auth=_AUTH)
        if hits:
            tool_context += "\n## Applicable Regulations (via MCP)\n"
            seen: set[str] = set()
            for hit in hits:
                if hit.reg_id not in seen:
                    tool_context += f"- [{hit.reg_id}] {hit.title}: {hit.text[:150]}\n"
                    seen.add(hit.reg_id)

    # ── Build prompt ─────────────────────────────────────────────────
    user_prompt = build_user_prompt(facts, context, coverage, settlement)
    if tool_context:
        user_prompt += tool_context

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await llm.generate(messages, response_schema=ComplianceVerdict)
        raw = json.loads(response["content"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ComplianceAgentError(
            AgentError(
                node="compliance",
                error_type="MalformedOutput",
                message=f"Could not parse LLM response: {exc}",
            )
        ) from exc

    if not isinstance(raw, dict):
        raise ComplianceAgentError(
            AgentError(
                node="compliance",
                error_type="MalformedOutput",
                message=f"Expected JSON object, got {type(raw).__name__}",
            )
        )

    passed = bool(raw.get("passed", True))
    violations = _extract_strings(raw.get("violations", []))
    rationale = str(raw.get("rationale", "")) or "No rationale provided."
    raw_citations: Any = raw.get("citations", [])
    citations = _parse_citations(raw_citations)

    # ComplianceVerdict validator: failed + no violations → invalid.
    if not passed and not violations:
        violations = ["Unspecified compliance violation"]

    return ComplianceVerdict(
        passed=passed,
        violations=violations,
        rationale=rationale,
        citations=citations,
    )


def _extract_strings(raw: Any) -> list[str]:
    """Extract a list of non-empty strings, tolerating bad data."""
    if not isinstance(raw, list):
        return []
    return [str(s) for s in raw if s]


def _parse_citations(raw: Any) -> list[Citation]:
    """Parse citation dicts, silently dropping invalid ones."""
    if not isinstance(raw, list):
        return []
    result: list[Citation] = []
    for rc in raw:
        if not isinstance(rc, dict):
            continue
        try:
            result.append(Citation(**rc))
        except Exception:  # noqa: BLE001, S112
            continue
    return result
