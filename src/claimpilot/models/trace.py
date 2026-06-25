"""Tracing and error models that power the audit trail."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from claimpilot.models.common import Citation


class StepTrace(BaseModel):
    """A single node's execution record appended to ClaimState.trace.

    ``inputs`` and ``outputs`` are intentionally typed as ``dict[str, Any]``
    because each graph node produces different Pydantic models; the trace
    stores their serialised snapshots for audit/eval replay.
    """

    node: str = Field(min_length=1)
    # Any justified: trace captures heterogeneous serialised agent I/O.
    inputs: dict[str, Any] = {}
    outputs: dict[str, Any] = {}
    citations: list[Citation] = []
    cost_usd: Decimal = Field(ge=Decimal(0), default=Decimal(0))
    latency_ms: float = Field(ge=0.0, default=0.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentError(BaseModel):
    """A typed error captured by the graph's error_handler node."""

    node: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)
    recoverable: bool = False
