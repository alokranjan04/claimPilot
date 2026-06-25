"""Fake queue — in-memory asyncio.Queue with ack tracking."""

from __future__ import annotations

import asyncio

from claimpilot.infra.interfaces import QueueMessage


class FakeQueue:
    """In-memory async queue backed by ``asyncio.Queue``.

    Messages stay in an *unacked* set after dequeue until ``ack`` is called,
    mirroring real broker semantics (at-least-once delivery).
    """

    def __init__(self) -> None:
        self._q: asyncio.Queue[QueueMessage] = asyncio.Queue()
        self._unacked: dict[str, QueueMessage] = {}

    async def enqueue(self, message: QueueMessage) -> None:
        await self._q.put(message)

    async def dequeue(self, *, timeout_seconds: float = 30.0) -> QueueMessage | None:
        try:
            msg = await asyncio.wait_for(self._q.get(), timeout=timeout_seconds)
        except TimeoutError:
            return None
        self._unacked[msg.id] = msg
        return msg

    async def ack(self, message_id: str) -> None:
        self._unacked.pop(message_id, None)
