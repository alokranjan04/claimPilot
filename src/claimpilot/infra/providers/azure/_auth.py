"""Credential helpers shared by all Azure providers.

For local development, pass an API key via the relevant ``*_api_key`` setting
and it will be used directly.  When the key is empty (CI, production, Managed
Identity), ``DefaultAzureCredential`` is used instead — no secrets required.
"""

from __future__ import annotations

from typing import Any


def get_credential(api_key: str = "") -> Any:
    """Return an ``AzureKeyCredential`` if *api_key* is set, else ``DefaultAzureCredential``.

    Use this for services that accept either credential type
    (AI Search, Document Intelligence, Cosmos DB …).
    """
    if api_key:
        from azure.core.credentials import AzureKeyCredential

        return AzureKeyCredential(api_key)

    from azure.identity.aio import DefaultAzureCredential

    return DefaultAzureCredential()
