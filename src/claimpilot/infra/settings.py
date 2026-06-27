"""Application settings loaded from environment via pydantic-settings.

The ``PROVIDER`` env var (default ``"fake"``) selects which set of
infrastructure implementations the DI factory wires up.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Root application configuration.

    All fields can be overridden by environment variables
    (case-insensitive, prefix-free for simplicity).
    """

    model_config = {
        "env_prefix": "",
        "case_sensitive": False,
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    # --- Provider selection ---------------------------------------------------
    provider: Literal["fake", "azure", "aws", "gcp"] = "fake"

    # --- LLM defaults ---------------------------------------------------------
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1024

    # --- Embedder defaults ----------------------------------------------------
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 64

    # --- Routing thresholds (Supervisor decision logic) -----------------------
    threshold_coverage_confidence: float = 0.75
    threshold_risk_score: float = 0.3
    threshold_max_auto_amount: Decimal = Decimal("10000")

    # --- Queue ----------------------------------------------------------------
    queue_timeout_seconds: float = 30.0

    # --- RAG pipeline ---------------------------------------------------------
    rag_k: int = 5
    rag_dense_weight: float = 0.6
    rag_lexical_weight: float = 0.4
    rag_tau_sufficient: float = 0.35
    rag_chunk_tokens: int = 450
    rag_chunk_overlap: int = 50

    # --- Fake provider options ------------------------------------------------
    fake_seed: int = 42

    # --- Azure OpenAI ---------------------------------------------------------
    # Set when PROVIDER=azure. Empty strings are safe defaults (unused with fake).
    aoai_endpoint: str = ""
    aoai_deployment_chat: str = "gpt-4o"
    aoai_deployment_embedding: str = "text-embedding-3-small"
    aoai_api_version: str = "2024-02-01"
    # Optional: API key for local dev. If empty, DefaultAzureCredential is used.
    # In production use Managed Identity (leave empty).
    aoai_api_key: str = ""

    # --- Azure AI Search ------------------------------------------------------
    azure_search_endpoint: str = ""
    azure_search_index: str = "claimpilot-chunks"
    azure_search_semantic_config: str = "claimpilot-semantic"
    # Optional: admin key for local dev. If empty, DefaultAzureCredential is used.
    azure_search_api_key: str = ""

    # --- Azure Document Intelligence ------------------------------------------
    azure_docintel_endpoint: str = ""
    # Optional: API key for local dev. If empty, DefaultAzureCredential is used.
    azure_docintel_api_key: str = ""

    # --- Azure Service Bus ----------------------------------------------------
    # Fully-qualified namespace, e.g. mynamespace.servicebus.windows.net
    azure_servicebus_namespace: str = ""
    azure_servicebus_queue: str = "claims"
    # Optional: full connection string for local dev (overrides namespace + credential).
    azure_servicebus_connection_string: str = ""

    # --- Azure Cosmos DB ------------------------------------------------------
    azure_cosmos_endpoint: str = ""
    azure_cosmos_database: str = "claimpilot"
    azure_cosmos_container: str = "checkpoints"
    # Optional: primary key for local dev. If empty, DefaultAzureCredential is used.
    azure_cosmos_key: str = ""

    # --- Azure Monitor --------------------------------------------------------
    # Application Insights connection string (set via env / Key Vault at deploy).
    azure_monitor_connection_string: str = ""
