"""Azure Cosmos DB implementation of :class:`~claimpilot.infra.interfaces.Checkpointer`.

Stores LangGraph pause/resume state as JSON documents in a Cosmos DB
container (serverless tier recommended).  Each checkpoint is a document with
``id = claim_id`` and ``state`` carrying the serialised graph state.

Partition key is set to ``/id`` — correct for per-claim isolation at scale.

Requires: ``uv sync --extra azure``
"""

from __future__ import annotations

import contextlib
from typing import Any


class AzureCosmosCheckpointer:
    """Persist and restore graph state snapshots in Azure Cosmos DB.

    Documents have the shape ``{"id": key, "state": <graph state dict>}``.
    ``load`` returns ``None`` if the document does not exist.
    ``delete`` is a no-op if the document has already been removed.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        database: str,
        container: str,
        key: str = "",
    ) -> None:
        try:
            from azure.cosmos.aio import CosmosClient
        except ImportError as exc:
            raise ImportError(
                "Azure provider requires extra dependencies: uv sync --extra azure"
            ) from exc

        # Any justified: CosmosClient uses a fluent builder that mypy can't
        # fully type without the SDK installed.
        if key:
            # Local dev: primary key from the portal.
            self._cosmos: Any = CosmosClient(url=endpoint, credential=key)
        else:
            # Production: DefaultAzureCredential (Managed Identity).
            try:
                from azure.identity.aio import DefaultAzureCredential
            except ImportError as exc:
                raise ImportError(
                    "Azure provider requires extra dependencies: uv sync --extra azure"
                ) from exc
            self._cosmos = CosmosClient(url=endpoint, credential=DefaultAzureCredential())
        self._database_name = database
        self._container_name = container
        # Lazily resolved on first call.
        self._container: Any | None = None

    async def _get_container(self) -> Any:
        """Lazily obtain the Cosmos container client."""
        if self._container is None:
            db = self._cosmos.get_database_client(self._database_name)
            self._container = db.get_container_client(self._container_name)
        return self._container

    async def save(self, key: str, state: dict[str, Any]) -> None:
        """Upsert *state* as a Cosmos document keyed by *key*."""
        container = await self._get_container()
        await container.upsert_item({"id": key, "state": state})

    async def load(self, key: str) -> dict[str, Any] | None:
        """Return the saved state or ``None`` if not found."""
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        container = await self._get_container()
        try:
            item: dict[str, Any] = await container.read_item(item=key, partition_key=key)
            state: dict[str, Any] = item.get("state", {})
            return state
        except CosmosResourceNotFoundError:
            return None

    async def delete(self, key: str) -> None:
        """Remove the checkpoint; silently ignores missing keys."""
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        container = await self._get_container()
        with contextlib.suppress(CosmosResourceNotFoundError):
            await container.delete_item(item=key, partition_key=key)
