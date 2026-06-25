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

    model_config = {"env_prefix": "", "case_sensitive": False}

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
    threshold_coverage_confidence: float = 0.8
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
