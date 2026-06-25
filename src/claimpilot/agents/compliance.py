"""Compliance/audit agent.

Pure async function:
``(ClaimFacts, PolicyContext, CoverageOpinion, SettlementProposal, LLMClient)
→ ComplianceVerdict``.
"""

from __future__ import annotations

import json
from typing import Any

from claimpilot.agents.prompts.compliance import SYSTEM_PROMPT, build_user_prompt
from claimpilot.infra.interfaces import LLMClient
from claimpilot.models.claim import ClaimFacts
from claimpilot.models.common import Citation
from claimpilot.models.decisions import (
    ComplianceVerdict,
    CoverageOpinion,
    PolicyContext,
    SettlementProposal,
)
from claimpilot.models.trace import AgentError


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
) -> ComplianceVerdict:
    """Review the adjudication for regulatory/policy compliance.

    Spec: master-spec §4 — Compliance/Audit agent row.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(facts, context, coverage, settlement)},
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
    # Guard against this by synthesising a violation.
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
