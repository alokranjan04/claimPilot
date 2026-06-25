"""Fake embedder — produces deterministic vectors via hashing."""

from __future__ import annotations

import hashlib
import struct


class FakeEmbedder:
    """Deterministic embedder that hashes input text into a fixed-dimension vector.

    The same text always produces the same embedding, making tests
    reproducible without any network calls.
    """

    def __init__(self, *, dims: int = 64, seed: int = 42) -> None:
        self._dims = dims
        self._seed = seed

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._dims

    def _embed_one(self, text: str) -> list[float]:
        """Hash *text* into a deterministic float vector of length *dims*."""
        h = hashlib.sha256(f"{self._seed}:{text}".encode()).digest()
        # Extend the hash to cover all dimensions.
        repeats = (self._dims * 4 // len(h)) + 1
        raw = (h * repeats)[: self._dims * 4]
        floats = list(struct.unpack(f"<{self._dims}f", raw))
        # Normalise to unit length for cosine similarity.
        norm = sum(x * x for x in floats) ** 0.5
        if norm == 0:
            return floats
        return [x / norm for x in floats]
