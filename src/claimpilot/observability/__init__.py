"""Observability: OTel-compatible spans, structured logging, and cost metering."""

from claimpilot.observability.cost_meter import ClaimCostSummary, compute_cost_summary
from claimpilot.observability.logging import configure_logging, get_logger
from claimpilot.observability.tracer import (
    InMemorySpanExporter,
    NoOpSpanExporter,
    SpanData,
    SpanExporter,
)

__all__ = [
    "ClaimCostSummary",
    "InMemorySpanExporter",
    "NoOpSpanExporter",
    "SpanData",
    "SpanExporter",
    "compute_cost_summary",
    "configure_logging",
    "get_logger",
]
