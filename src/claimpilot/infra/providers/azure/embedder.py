"""Azure OpenAI implementation of :class:`~claimpilot.infra.interfaces.Embedder`.

Uses the ``openai`` SDK's embeddings endpoint backed by an Azure OpenAI
deployment (e.g. ``text-embedding-3-small``).

Requires: ``uv sync --extra azure``
"""

from __future__ import annotations

from typing import Any


class AzureOpenAIEmbedder:
    """Produces embeddings via an Azure OpenAI text-embedding deployment.

    The ``dimensions`` property reflects the configured embedding size
    (defaults to 1536 for ``text-embedding-3-small``).
    """

    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str = "text-embedding-3-small",
        api_version: str = "2024-02-01",
        dims: int = 1536,
    ) -> None:
        try:
            from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
            from openai import AsyncAzureOpenAI
        except ImportError as exc:
            raise ImportError(
                "Azure provider requires extra dependencies: uv sync --extra azure"
            ) from exc

        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        # Any justified: openai SDK is untyped at the attribute level.
        self._client: Any = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
            api_version=api_version,
        )
        self._deployment = deployment
        self._dims = dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        if not texts:
            return []
        response = await self._client.embeddings.create(
            model=self._deployment,
            input=texts,
        )
        # Sort by index to preserve order (API may reorder).
        items = sorted(response.data, key=lambda d: d.index)
        return [item.embedding for item in items]

    @property
    def dimensions(self) -> int:
        """Dimensionality of vectors produced by this embedder."""
        return self._dims
