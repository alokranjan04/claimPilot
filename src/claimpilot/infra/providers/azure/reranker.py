"""Azure AI Search semantic reranker implementation of
:class:`~claimpilot.infra.interfaces.Reranker`.

Uses Azure AI Search's L2 semantic reranker (``query_type="semantic"``) to
re-score and re-order candidate hits.  The semantic configuration must be
provisioned on the index by the Bicep IaC.

Requires: ``uv sync --extra azure``
"""

from __future__ import annotations

import contextlib
from typing import Any

from claimpilot.infra.interfaces import SearchHit


class AzureSearchReranker:
    """Re-score candidate hits using Azure AI Search semantic ranker.

    Sends the original text + query to the semantic ranker endpoint
    and returns hits sorted by the ``@search.reranker_score``.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        index_name: str,
        semantic_config: str = "claimpilot-semantic",
        vector_field: str = "embedding",
    ) -> None:
        try:
            from azure.identity.aio import DefaultAzureCredential
            from azure.search.documents.aio import SearchClient
        except ImportError as exc:
            raise ImportError(
                "Azure provider requires extra dependencies: uv sync --extra azure"
            ) from exc

        # Any justified: azure-search-documents SDK has dynamic return types.
        self._client: Any = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=DefaultAzureCredential(),
        )
        self._semantic_config = semantic_config
        self._vector_field = vector_field

    async def rerank(
        self,
        query: str,
        hits: list[SearchHit],
        *,
        top_k: int = 5,
    ) -> list[SearchHit]:
        """Re-score *hits* using the Azure AI Search semantic ranker.

        If *hits* is empty, returns immediately.  The IDs in *hits* are used
        to scope the semantic search (via OData ``search.in`` filter) so we
        only rerank the candidates already retrieved, not the full index.
        """
        if not hits:
            return []

        from azure.search.documents.models import VectorizedQuery

        # Build an ID filter so semantic reranker only scores our candidates.
        id_list = ", ".join(f"'{h.id}'" for h in hits)
        odata_filter = f"search.in(id, '{id_list}', ',')"

        # Use a dummy zero-vector for the vector query to retrieve by filter;
        # the semantic ranker will re-score by text relevance.
        dummy_vec = [0.0] * (len(hits[0].score) if False else 1536)  # noqa: SIM210
        vector_query = VectorizedQuery(
            vector=dummy_vec,
            k_nearest_neighbors=len(hits),
            fields=self._vector_field,
        )
        results = self._client.search(
            search_text=query,
            vector_queries=[vector_query],
            filter=odata_filter,
            query_type="semantic",
            semantic_configuration_name=self._semantic_config,
            top=top_k,
        )

        reranked: list[SearchHit] = []
        async for doc in results:
            import json

            raw_meta = doc.get("metadata", "{}")
            metadata: dict[str, str] = {}
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                metadata = json.loads(raw_meta)
            reranked.append(
                SearchHit(
                    id=str(doc["id"]),
                    text=str(doc.get("text", "")),
                    score=float(doc.get("@search.reranker_score") or doc.get("@search.score", 0.0)),
                    metadata=metadata,
                )
            )
        return reranked[:top_k]
