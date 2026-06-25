"""Fake checkpointer — in-memory dict for graph state persistence."""

from __future__ import annotations

import copy
from typing import Any


class FakeCheckpointer:
    """In-memory checkpoint store backed by a plain dict.

    Deep-copies values on save/load to mimic real serialisation boundaries
    and catch mutations that would be invisible with pass-by-reference.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def save(self, key: str, state: dict[str, Any]) -> None:
        self._store[key] = copy.deepcopy(state)

    async def load(self, key: str) -> dict[str, Any] | None:
        data = self._store.get(key)
        if data is None:
            return None
        return copy.deepcopy(data)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
