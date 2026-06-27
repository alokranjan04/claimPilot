"""Structured JSON logging with per-claim context and PII filtering.

Design rules (master-spec §12):
  - Every log record carries ``claim_id`` for end-to-end traceability.
  - PII and raw prompt / response content are **never** logged at INFO or below.
  - Output is newline-delimited JSON for log aggregators (Grafana, Azure Monitor).

Usage::

    from claimpilot.observability.logging import configure_logging, get_logger

    configure_logging()          # once at startup
    log = get_logger("CLM-001")
    log.info("node_completed", node="intake", latency_ms=12.3)
    # → {"log_level": "info", "claim_id": "CLM-001", "node": "intake",
    #    "latency_ms": 12.3, "timestamp": "2025-...", "event": "node_completed"}
"""

from __future__ import annotations

import sys
from typing import Any

import structlog

# Fields that must never appear in log output (PII / raw LLM I/O).
_PII_KEYS: frozenset[str] = frozenset(
    {
        "claimant",
        "fnol_text",
        "messages",
        "name",
        "parties",
        "prompt",
        "raw_input",
        "response_text",
    }
)


def _drop_pii(
    logger: Any,  # Any: structlog processor receives heterogeneous logger types
    method: str,  # Any: structlog processor signature requirement
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor: strip PII keys before the record is rendered.

    Runs in the processor chain so no PII ever reaches the output sink,
    regardless of which log level or sink is configured.
    """
    for key in _PII_KEYS:
        event_dict.pop(key, None)
    return event_dict


def configure_logging(*, json_output: bool = True) -> None:
    """Configure structlog for structured output.

    Parameters
    ----------
    json_output:
        ``True`` (default) for newline-delimited JSON.
        ``False`` for human-friendly console rendering (useful in development).

    Safe to call multiple times — structlog's global config is replaced on
    each call, so tests can re-configure without side effects.
    """
    processors: list[Any] = [  # Any: structlog processor protocol is broad
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _drop_pii,
    ]
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(claim_id: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger, optionally bound with ``claim_id``.

    Parameters
    ----------
    claim_id:
        The claim being processed.  When provided it is bound as a context
        variable so every log record from this logger carries the ID without
        the caller needing to pass it explicitly.

    Example::

        log = get_logger("CLM-00001")
        log.info("node_completed", node="intake", latency_ms=12.3)
    """
    log: structlog.stdlib.BoundLogger = structlog.get_logger()
    if claim_id is not None:
        log = log.bind(claim_id=claim_id)
    return log
