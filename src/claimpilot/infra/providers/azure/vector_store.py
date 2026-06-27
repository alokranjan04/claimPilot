"""Azure AI Search implementation of :class:`~claimpilot.infra.interfaces.VectorStore`.

Uses ``azure-search-documents`` with HNSW vector indexing.  The index is
expected to be provisioned by the Bicep IaC in ``infra/iac/main.bicep``
before the provider is used.

Field schema expected on the index:
  - ``id``        (Edm.String, key)
  - ``text``      (Edm.String, searchable)
  - ``embedding`` (Collection(Edm.Single), vector, 1536-dim HNSW)
  - ``metadata``  (Edm.String) — JSON-serialised metadata dict

Requires: ``uv sync --extra azure``
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from claimpilot.infra.interfaces import SearchHit, VectorRecord


class AzureSearchVectorStore:
    """Azure AI Search-backed vector store.

    Upserts and queries use the REST API via ``SearchClient``.  Metadata is
    stored as a JSON string in the ``metadata`` field so the index schema
    remains fixed regardless of which metadata keys RAG chunks carry.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        index_name: str,
        embedding_dimensions: int = 1536,
        vector_field: str = "embedding",
    ) -> None:
        try:
            from azure.identity.aio import DefaultAzureCredential
            from azure.search.documents.aio import SearchClient
        except ImportError as exc:
            raise ImportError(
                "Azure provider requires extra dependencies: uv sync --extra azure"
            ) from exc

        # Any justified: azure-search-documents SDK uses typed internals but
        # the top-level client exposes dynamic attributes.
        self._client: Any = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=DefaultAzureCredential(),
        )
        self._vector_field = vector_field
        self._embedding_dimensions = embedding_dimensions

    async def upsert(self, records: list[VectorRecord]) -> None:
        """Upload or update documents in the AI Search index."""
        if not records:
            return
        docs = [
            {
                "id": rec.id,
                "text": rec.text,
                self._vector_field: rec.embedding,
                "metadata": json.dumps(rec.metadata),
            }
            for rec in records
        ]
        await self._client.upload_documents(documents=docs)

    async def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        filter_metadata: dict[str, str] | None = None,
    ) -> list[SearchHit]:
        """Return the *top_k* most similar documents via HNSW vector search."""
        from azure.search.documents.models import VectorizedQuery

        vector_query = VectorizedQuery(
            vector=query_embedding,
            k_nearest_neighbors=top_k,
            fields=self._vector_field,
        )
        # Build OData filter from metadata dict if provided.
        odata_filter: str | None = None
        if filter_metadata:
            # We store metadata as a JSON blob; exact-match filtering is not
            # possible on arbitrary keys.  Callers should use sparse metadata
            # or rely on post-filtering.  Log a warning and skip for now.
            pass

        results = self._client.search(
            search_text=None,
            vector_queries=[vector_query],
            top=top_k,
            filter=odata_filter,
        )
        hits: list[SearchHit] = []
        async for doc in results:
            raw_meta = doc.get("metadata", "{}")
            metadata: dict[str, str] = {}
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                metadata = json.loads(raw_meta)
            # Apply in-memory metadata filter when OData filter is not possible.
            if filter_metadata and not all(
                metadata.get(k) == v for k, v in filter_metadata.items()
            ):
                continue
            hits.append(
                SearchHit(
                    id=str(doc["id"]),
                    text=str(doc.get("text", "")),
                    score=float(doc.get("@search.score", 0.0)),
                    metadata=metadata,
                )
            )
        return hits[:top_k]

    async def delete(self, ids: list[str]) -> None:
        """Remove documents from the index by id."""
        if not ids:
            return
        docs = [{"id": id_} for id_ in ids]
        await self._client.delete_documents(documents=docs)
