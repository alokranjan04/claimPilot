"""Per-claim cost and latency aggregation from :class:`~claimpilot.models.trace.StepTrace`.

Cost model uses token-based pricing (GPT-4o tier, mid-2025 list prices).
For the fake LLM, ``cost_usd`` defaults to ``Decimal(0)`` per node because
no real API call is made; real providers populate it via the token usage
reported in the LLM response.

Usage::

    from claimpilot.observability.cost_meter import compute_cost_summary

    summary = compute_cost_summary("CLM-001", state["trace"])
    print(summary.total_cost_usd)    # Decimal("0.00") with fakes
    print(summary.total_latency_ms)  # float: sum of per-node measured latencies
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from claimpilot.models.trace import StepTrace

# Rough pricing proxy (GPT-4o tier, mid-2025).  Only matters with real providers;
# fake LLM produces cost_usd=Decimal(0) per node so totals stay at zero.
COST_PER_PROMPT_TOKEN: Decimal = Decimal("0.000005")  # $5 / 1M input tokens
COST_PER_COMPLETION_TOKEN: Decimal = Decimal("0.000015")  # $15 / 1M output tokens


class ClaimCostSummary(BaseModel):
    """Per-claim cost and latency rolled up from the graph ``trace`` list."""

    claim_id: str
    total_cost_usd: Decimal = Field(default=Decimal(0), ge=Decimal(0))
    total_latency_ms: float = Field(default=0.0, ge=0.0)
    node_count: int = Field(default=0, ge=0)

    # Decimal serialised as string in JSON mode (Pydantic v2 Decimal → str).
    cost_by_node: dict[str, str] = Field(default_factory=dict)
    latency_by_node: dict[str, float] = Field(default_factory=dict)


def compute_cost_summary(claim_id: str, trace: list[StepTrace]) -> ClaimCostSummary:
    """Aggregate ``cost_usd`` and ``latency_ms`` across all :class:`StepTrace` records.

    Parameters
    ----------
    claim_id:
        Identifier of the claim being summarised.
    trace:
        The ``trace`` list from the final graph state.  If the same logical
        node appears more than once (e.g. after an error retry), its costs and
        latencies are summed.

    Returns
    -------
    ClaimCostSummary
        Totals and per-node breakdowns.  All Decimal values are serialised as
        strings in JSON mode so they round-trip without floating-point loss.
    """
    total_cost: Decimal = Decimal(0)
    total_latency: float = 0.0
    cost_by_node: dict[str, Decimal] = {}
    latency_by_node: dict[str, float] = {}

    for step in trace:
        node = step.node
        cost_by_node[node] = cost_by_node.get(node, Decimal(0)) + step.cost_usd
        latency_by_node[node] = latency_by_node.get(node, 0.0) + step.latency_ms
        total_cost += step.cost_usd
        total_latency += step.latency_ms

    return ClaimCostSummary(
        claim_id=claim_id,
        total_cost_usd=total_cost,
        total_latency_ms=total_latency,
        node_count=len(trace),
        cost_by_node={k: str(v) for k, v in cost_by_node.items()},
        latency_by_node=latency_by_node,
    )
