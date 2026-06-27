"""Azure OpenAI implementation of :class:`~claimpilot.infra.interfaces.LLMClient`.

Uses the ``openai`` SDK with ``azure-identity`` Entra ID authentication
(no API keys — Managed Identity in production, DefaultAzureCredential locally).

Requires: ``uv sync --extra azure``
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class AzureOpenAILLMClient:
    """Calls Azure OpenAI chat completions via the ``openai`` SDK.

    Authentication is handled by ``DefaultAzureCredential`` from
    ``azure-identity`` — no API keys needed when Managed Identity is
    configured.  Locally, ``az login`` satisfies the credential.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str,
        api_version: str = "2024-02-01",
        api_key: str = "",
    ) -> None:
        try:
            from openai import AsyncAzureOpenAI
        except ImportError as exc:
            raise ImportError(
                "Azure provider requires extra dependencies: uv sync --extra azure"
            ) from exc

        # Any justified: openai SDK is untyped at the attribute level.
        if api_key:
            # Local dev: use the API key directly — no identity credential needed.
            self._client: Any = AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=api_version,
            )
        else:
            # Production / CI: DefaultAzureCredential (Managed Identity, az login …).
            try:
                from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
            except ImportError as exc:
                raise ImportError(
                    "Azure provider requires extra dependencies: uv sync --extra azure"
                ) from exc
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            self._client = AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                azure_ad_token_provider=token_provider,
                api_version=api_version,
            )
        self._deployment = deployment

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_schema: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        """Call Azure OpenAI and return ``{"content": ..., "usage": {...}}``."""
        kwargs: dict[str, Any] = {
            "model": model or self._deployment,
            "messages": messages,
            "temperature": temperature,
            # Newer models (gpt-5.x, o-series) require max_completion_tokens;
            # max_tokens is deprecated.  Use the new parameter for all models.
            "max_completion_tokens": max_tokens,
        }
        if response_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self._client.chat.completions.create(**kwargs)

        content_raw: str = response.choices[0].message.content or ""
        # Validate structured output parses correctly (surface errors early).
        if response_schema is not None:
            try:
                json.loads(content_raw)
            except json.JSONDecodeError:
                content_raw = json.dumps({"_parse_error": True, "raw": content_raw})

        usage = response.usage
        return {
            "content": content_raw,
            "usage": {
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
            },
        }
