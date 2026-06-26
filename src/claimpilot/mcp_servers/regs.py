"""regs MCP server — search regulatory text by jurisdiction and topic.

Tools:
    search(jurisdiction, topic) → list[RegHit]
"""

from __future__ import annotations

from pydantic import BaseModel

from claimpilot.mcp_servers.base import AuthContext, ToolError


class RegHit(BaseModel):
    """A matching regulatory passage."""

    reg_id: str
    jurisdiction: str
    title: str
    text: str


class RegsServer:
    """In-memory regs MCP server backed by fixture regulatory text."""

    def __init__(self, regulations: list[RegHit] | None = None) -> None:
        self._regs: list[RegHit] = regulations or _default_regs()

    def search(
        self,
        jurisdiction: str,
        topic: str,
        *,
        auth: AuthContext,
    ) -> list[RegHit]:
        """Search regulations by jurisdiction and topic keyword."""
        _check_auth(auth, "regs.search")
        if not jurisdiction:
            raise ToolError("regs.search", "jurisdiction must not be empty")
        if not topic:
            raise ToolError("regs.search", "topic must not be empty")

        topic_lower = topic.lower()
        return [
            r
            for r in self._regs
            if r.jurisdiction.lower() == jurisdiction.lower() and topic_lower in r.text.lower()
        ]


def _check_auth(auth: AuthContext, tool: str) -> None:
    if not auth.caller:
        raise ToolError(tool, "missing caller in auth context")


def _default_regs() -> list[RegHit]:
    return [
        RegHit(
            reg_id="§R.1",
            jurisdiction="IL",
            title="Timely Processing",
            text=(
                "All claims must be acknowledged within 15 business days. "
                "Decision within 45 calendar days unless investigation documented."
            ),
        ),
        RegHit(
            reg_id="§R.2",
            jurisdiction="IL",
            title="Fair Settlement Practices",
            text=(
                "Settlements must reflect actual cash value or replacement cost. "
                "Low-ball offers are a violation."
            ),
        ),
        RegHit(
            reg_id="§R.3",
            jurisdiction="IL",
            title="Anti-Fraud Requirements",
            text=(
                "Insurers must maintain a special investigations unit (SIU) and "
                "report suspected fraud within 60 days of detection."
            ),
        ),
    ]
