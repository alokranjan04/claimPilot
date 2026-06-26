"""FastAPI dependency functions — pull shared state from ``app.state``."""

from __future__ import annotations

from fastapi import Request

from claimpilot.api.worker import ClaimStore, EventBus
from claimpilot.infra.interfaces import Queue
from claimpilot.infra.settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_queue(request: Request) -> Queue:
    return request.app.state.queue  # type: ignore[no-any-return]


def get_claim_store(request: Request) -> ClaimStore:
    return request.app.state.store  # type: ignore[no-any-return]


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.bus  # type: ignore[no-any-return]
