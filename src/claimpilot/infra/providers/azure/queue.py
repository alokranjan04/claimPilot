"""Azure Service Bus implementation of :class:`~claimpilot.infra.interfaces.Queue`.

Uses the async ``azure-servicebus`` SDK with ``DefaultAzureCredential`` (no
connection-string secrets).  A persistent receiver is kept alive between
``dequeue`` calls to maintain message locks for at-least-once delivery.

Requires: ``uv sync --extra azure``
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from claimpilot.infra.interfaces import QueueMessage


class AzureServiceBusQueue:
    """Async Service Bus queue adapter.

    ``enqueue`` creates a new sender context per call (stateless).
    ``dequeue`` uses a persistent receiver to hold the peek-lock across
    the ``ack`` call.  ``ack`` completes (settles) the message, releasing
    the lock to the broker.

    The receiver is lazily created on first ``dequeue`` and kept alive.
    """

    def __init__(
        self,
        *,
        namespace: str,
        queue_name: str,
        connection_string: str = "",
    ) -> None:
        try:
            from azure.servicebus.aio import ServiceBusClient
        except ImportError as exc:
            raise ImportError(
                "Azure provider requires extra dependencies: uv sync --extra azure"
            ) from exc

        # Any justified: azure-servicebus SDK uses dynamic client factory.
        if connection_string:
            # Local dev: full connection string from the portal.
            self._sb_client: Any = ServiceBusClient.from_connection_string(connection_string)
        else:
            # Production: DefaultAzureCredential (Managed Identity).
            try:
                from azure.identity.aio import DefaultAzureCredential
            except ImportError as exc:
                raise ImportError(
                    "Azure provider requires extra dependencies: uv sync --extra azure"
                ) from exc
            self._sb_client = ServiceBusClient(
                fully_qualified_namespace=namespace,
                credential=DefaultAzureCredential(),
            )
        self._queue_name = queue_name
        # Persistent receiver; created lazily on first dequeue.
        self._receiver: Any | None = None
        # Maps our message_id → ServiceBusReceivedMessage for ack.
        self._pending: dict[str, Any] = {}

    async def enqueue(self, message: QueueMessage) -> None:
        """Send *message* to the Service Bus queue."""
        from azure.servicebus import ServiceBusMessage

        async with self._sb_client.get_queue_sender(queue_name=self._queue_name) as sender:
            sb_msg = ServiceBusMessage(
                body=json.dumps(message.body),
                message_id=message.id,
            )
            await sender.send_messages(sb_msg)

    async def dequeue(self, *, timeout_seconds: float = 30.0) -> QueueMessage | None:
        """Receive one message, or ``None`` if the timeout elapses."""
        if self._receiver is None:
            self._receiver = self._sb_client.get_queue_receiver(
                queue_name=self._queue_name,
                max_wait_time=int(timeout_seconds),
            )

        received = await self._receiver.receive_messages(
            max_message_count=1,
            max_wait_time=int(timeout_seconds),
        )
        if not received:
            return None

        sb_msg = received[0]
        # Body is a generator of bytes chunks; join and decode.
        body_bytes = b"".join(sb_msg.body)
        body: dict[str, Any] = json.loads(body_bytes.decode("utf-8"))

        msg_id = str(sb_msg.message_id) if sb_msg.message_id else str(uuid.uuid4())
        self._pending[msg_id] = sb_msg
        return QueueMessage(id=msg_id, body=body)

    async def ack(self, message_id: str) -> None:
        """Complete (settle) *message_id*, releasing it from the queue."""
        sb_msg = self._pending.pop(message_id, None)
        if sb_msg is not None and self._receiver is not None:
            await self._receiver.complete_message(sb_msg)
