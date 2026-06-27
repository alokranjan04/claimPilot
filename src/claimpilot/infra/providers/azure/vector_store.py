"""Azure AI Search implementation of :class:`~claimpilot.infra.interfaces.VectorStore`.

Uses ``azure-search-documents`` with HNSW vector indexing.  The index is
auto-created on first ``upsert`` if it does not already exist.

Field schema on the index:
  - ``id``        (Edm.String, key)
  - ``text``      (Edm.String, searchable)
  - ``embedding`` (Collection(Edm.Single), vector, HNSW)
  - ``metadata``  (Edm.String) — JSON-serialised metadata dict

Requires: ``uv sync --extra azure``
"""

from __future__ import annotations

import base64
import contextlib
import json
from typing import Any

from claimpilot.infra.interfaces import SearchHit, VectorRecord


class AzureSearchVectorStore:
    """Azure AI Search-backed vector store.

    Upserts and queries use the REST API via ``SearchClient``.  Metadata is
    stored as a JSON string in the ``metadata`` field so the index schema
    remains fixed regardless of which metadata keys RAG chunks carry.

    On first ``upsert`` the index is created automatically if it doesn't exist.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        index_name: str,
        embedding_dimensions: int = 1536,
        vector_field: str = "embedding",
        api_key: str = "",
    ) -> None:
        try:
            from azure.search.documents.aio import SearchClient
        except ImportError as exc:
            raise ImportError(
                "Azure provider requires extra dependencies: uv sync --extra azure"
            ) from exc

        from claimpilot.infra.providers.azure._auth import get_credential

        credential = get_credential(api_key)
        # Any justified: azure-search-documents SDK uses typed internals but
        # the top-level client exposes dynamic attributes.
        self._client: Any = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=credential,
        )
        self._endpoint = endpoint
        self._index_name = index_name
        self._credential = credential
        self._vector_field = vector_field
        self._embedding_dimensions = embedding_dimensions
        self._index_ensured = False

    async def _ensure_index(self) -> None:
        """Create the search index if it does not already exist."""
        if self._index_ensured:
            return

        from azure.search.documents.indexes.aio import SearchIndexClient
        from azure.search.documents.indexes.models import (
            HnswAlgorithmConfiguration,
            SearchableField,
            SearchField,
            SearchIndex,
            SemanticConfiguration,
            SemanticField,
            SemanticPrioritizedFields,
            SemanticSearch,
            SimpleField,
            VectorSearch,
            VectorSearchProfile,
        )

        index_client: Any = SearchIndexClient(
            endpoint=self._endpoint,
            credential=self._credential,
        )
        try:
            # Check if index already exists.
            await index_client.get_index(self._index_name)
            self._index_ensured = True
            return
        except Exception:  # noqa: S110
            pass  # Index doesn't exist — create it below.

        fields = [
            SimpleField(
                name="id",
                type="Edm.String",
                key=True,
                filterable=True,
            ),
            SearchableField(
                name="text",
                type="Edm.String",
            ),
            SearchField(
                name=self._vector_field,
                type="Collection(Edm.Single)",
                searchable=True,
                vector_search_dimensions=self._embedding_dimensions,
                vector_search_profile_name="default-profile",
            ),
            SimpleField(
                name="metadata",
                type="Edm.String",
            ),
        ]

        vector_search = VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="default-algo")],
            profiles=[
                VectorSearchProfile(
                    name="default-profile",
                    algorithm_configuration_name="default-algo",
                )
            ],
        )

        semantic_config = SemanticConfiguration(
            name="claimpilot-semantic",
            prioritized_fields=SemanticPrioritizedFields(
                content_fields=[SemanticField(field_name="text")],
            ),
        )
        semantic_search = SemanticSearch(configurations=[semantic_config])

        index = SearchIndex(
            name=self._index_name,
            fields=fields,
            vector_search=vector_search,
            semantic_search=semantic_search,
        )
        await index_client.create_index(index)
        self._index_ensured = True

    async def upsert(self, records: list[VectorRecord]) -> None:
        """Upload or update documents in the AI Search index."""
        if not records:
            return
        await self._ensure_index()
        docs = [
            {
                "id": _encode_key(rec.id),
                "text": rec.text,
                self._vector_field: rec.embedding,
                "metadata": json.dumps({**rec.metadata, "_original_id": rec.id}),
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

        results = await self._client.search(
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
            # Recover original ID from metadata or decode the key.
            original_id = metadata.pop("_original_id", None) or _decode_key(str(doc["id"]))
            hits.append(
                SearchHit(
                    id=original_id,
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
        docs = [{"id": _encode_key(id_)} for id_ in ids]
        await self._client.delete_documents(documents=docs)


def _encode_key(key: str) -> str:
    """URL-safe Base64 encode a document key for AI Search compatibility."""
    return base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")


def _decode_key(encoded: str) -> str:
    """Decode a URL-safe Base64 encoded document key, or return as-is if invalid."""
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        return base64.urlsafe_b64decode(padded.encode()).decode()
    except (UnicodeDecodeError, ValueError):
        return encoded
