"""Azure Monitor / Application Insights span exporter for ClaimPilot.

Bridges our custom :class:`~claimpilot.observability.tracer.SpanData` model
to the OpenTelemetry pipeline configured by ``azure-monitor-opentelemetry``.

Usage::

    from claimpilot.observability.azure_exporter import AzureMonitorSpanExporter
    from claimpilot.graph.build_graph import build_graph

    exporter = AzureMonitorSpanExporter(
        connection_string=settings.azure_monitor_connection_string
    )
    graph = build_graph(..., span_exporter=exporter)

On each node completion, the exporter creates an OTel span carrying the
claim_id, node name, latency, and error status — visible in Application
Insights as "custom telemetry / spans".

Requires: ``uv sync --extra azure``
"""

from __future__ import annotations

from typing import Any

from claimpilot.observability.tracer import SpanData


class AzureMonitorSpanExporter:
    """Export :class:`~claimpilot.observability.tracer.SpanData` to Azure Monitor.

    Calls ``configure_azure_monitor`` once at initialisation to wire the
    OpenTelemetry SDK pipeline (tracer provider + Azure Monitor exporter).
    Each ``export`` call creates an OTel span via the configured tracer,
    sets attributes (claim_id, node, latency, error) and ends it immediately.

    Note: the span end-time is set at export time (not at the original node
    end-time) because OTel SDK manages span timing internally.  The
    ``duration_ms`` attribute carries the true measured latency.
    """

    def __init__(self, *, connection_string: str) -> None:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor
            from opentelemetry import trace
        except ImportError as exc:
            raise ImportError(
                "Azure Monitor exporter requires extra dependencies: uv sync --extra azure"
            ) from exc

        configure_azure_monitor(connection_string=connection_string)
        # Any justified: OTel Tracer has a dynamic attribute API.
        self._tracer: Any = trace.get_tracer(
            "claimpilot",
            tracer_provider=trace.get_tracer_provider(),
        )

    def export(self, span: SpanData) -> None:
        """Create an OTel span for *span* and end it, flushing to Azure Monitor."""
        from opentelemetry.trace import Status, StatusCode

        attributes: dict[str, str | float | bool] = {
            "claim.id": span.claim_id,
            "node.name": span.name,
            "node.duration_ms": span.duration_ms,
        }
        for k, v in span.attributes.items():
            attributes[f"custom.{k}"] = str(v)

        with self._tracer.start_as_current_span(
            span.name,
            attributes=attributes,
        ) as otel_span:
            if not span.status_ok:
                otel_span.set_status(
                    Status(StatusCode.ERROR, span.error_message or "unknown error")
                )
