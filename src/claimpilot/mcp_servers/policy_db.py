"""policy-db MCP server — search and get_clause over the policy corpus.

Tools:
    search(query, policy_id) → list[ClauseHit]
    get_clause(clause_id)    → ClauseDetail | None
"""

from __future__ import annotations

from pydantic import BaseModel

from claimpilot.mcp_servers.base import AuthContext, ToolError


class ClauseHit(BaseModel):
    """A search result from the policy corpus."""

    clause_id: str
    document: str
    snippet: str
    score: float = 0.0


class ClauseDetail(BaseModel):
    """Full text of a single clause."""

    clause_id: str
    document: str
    text: str
    metadata: dict[str, str] = {}


class PolicyDbServer:
    """In-memory policy-db MCP server backed by a fixture dict."""

    def __init__(self, clauses: dict[str, ClauseDetail] | None = None) -> None:
        self._clauses: dict[str, ClauseDetail] = clauses or _default_clauses()

    def search(
        self,
        query: str,
        *,
        policy_id: str | None = None,
        auth: AuthContext,
    ) -> list[ClauseHit]:
        """Search clauses by keyword match."""
        _check_auth(auth, "policy_db.search")
        if not query:
            raise ToolError("policy_db.search", "query must not be empty")

        results: list[ClauseHit] = []
        query_lower = query.lower()
        for clause in self._clauses.values():
            if policy_id and not clause.clause_id.startswith(policy_id):
                continue
            if query_lower in clause.text.lower():
                results.append(
                    ClauseHit(
                        clause_id=clause.clause_id,
                        document=clause.document,
                        snippet=clause.text[:200],
                        score=1.0,
                    )
                )
        return results

    def get_clause(
        self,
        clause_id: str,
        *,
        auth: AuthContext,
    ) -> ClauseDetail | None:
        """Retrieve a specific clause by ID."""
        _check_auth(auth, "policy_db.get_clause")
        if not clause_id:
            raise ToolError("policy_db.get_clause", "clause_id must not be empty")
        return self._clauses.get(clause_id)


def _check_auth(auth: AuthContext, tool: str) -> None:
    if not auth.caller:
        raise ToolError(tool, "missing caller in auth context")


def _default_clauses() -> dict[str, ClauseDetail]:
    return {
        "§1.1": ClauseDetail(
            clause_id="§1.1",
            document="Standard Auto Policy",
            text="Comprehensive coverage: collisions, theft, vandalism, weather. Deductible $500.",
            metadata={"policy_type": "auto"},
        ),
        "§1.3": ClauseDetail(
            clause_id="§1.3",
            document="Standard Auto Policy",
            text="Exclusions: intentional damage, racing, commercial use, wear and tear.",
            metadata={"policy_type": "auto"},
        ),
    }
