"""OTel-compatible span tracer for ClaimPilot graph nodes.

Defines a provider-agnostic ``SpanExporter`` protocol so tests can use the
``InMemorySpanExporter`` without any cloud dependency.  The real Azure Monitor
exporter is wired at M10 (``azure-monitor-opentelemetry``).

Span IDs / trace IDs are random hex strings compatible with OpenTelemetry's
128-bit trace-ID / 64-bit span-ID wire format.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class SpanData(BaseModel):
    """Immutable record of a single node execution — the OTel-compatible span."""

    span_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:32])
    name: str  # graph node name
    claim_id: str
    start_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = Field(default=0.0, ge=0.0)
    # Any justified: span attributes are heterogeneous (str / int / float / bool).
    attributes: dict[str, Any] = Field(default_factory=dict)
    status_ok: bool = True
    error_message: str | None = None


@runtime_checkable
class SpanExporter(Protocol):
    """Export a completed span to a backend (no-op, in-memory, Azure Monitor …)."""

    def export(self, span: SpanData) -> None:
        """Persist or transmit the span to the configured backend."""
        ...  # pragma: no cover


class NoOpSpanExporter:
    """Default exporter — silently discards every span (zero overhead)."""

    def export(self, span: SpanData) -> None:
        pass


class InMemorySpanExporter:
    """Accumulates :class:`SpanData` in a list for test assertions.

    Example::

        exporter = InMemorySpanExporter()
        graph = build_graph(..., span_exporter=exporter)
        await graph.ainvoke(...)
        assert "intake" in exporter.names()
    """

    def __init__(self) -> None:
        self.spans: list[SpanData] = []

    def export(self, span: SpanData) -> None:
        self.spans.append(span)

    def clear(self) -> None:
        """Remove all accumulated spans."""
        self.spans.clear()

    def names(self) -> list[str]:
        """Return node names of collected spans in emission order."""
        return [s.name for s in self.spans]
