"""Fake LLM client — scriptable responses with deterministic hash fallback."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any

from pydantic import BaseModel


class FakeLLMClient:
    """In-memory LLM that returns scripted or deterministic responses.

    Three response-resolution strategies, checked in order:

    1. **Scripted queue** — ``scripted=[r1, r2, ...]`` responses are consumed
       FIFO.  When the queue is exhausted, falls through to the next strategy.
    2. **Response map** — ``response_map={"key_substring": response, ...}``
       matches the first entry whose key appears in the concatenated prompt.
    3. **Hash fallback** — deterministic hash-based output seeded by ``seed``,
       ensuring "same input → same output" stability for any call not
       covered by scripts.

    Each *response* in the scripted queue or map can be:
    - A ``dict`` — returned directly as the ``"content"`` value (serialised
      to JSON).  Ideal for structured-output tests.
    - A ``BaseModel`` instance — serialised via ``.model_dump()`` then JSON.
    - A ``str`` — returned verbatim as ``"content"``.
    """

    def __init__(
        self,
        *,
        seed: int = 42,
        scripted: list[dict[str, Any] | BaseModel | str] | None = None,
        response_map: dict[str, dict[str, Any] | BaseModel | str] | None = None,
    ) -> None:
        self._seed = seed
        self._call_count = 0
        self._scripted: deque[dict[str, Any] | BaseModel | str] = deque(scripted or [])
        self._response_map: dict[str, dict[str, Any] | BaseModel | str] = response_map or {}

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_schema: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        self._call_count += 1
        prompt_text = " ".join(m.get("content", "") for m in messages)

        content = self._resolve(prompt_text, response_schema)

        prompt_tokens = sum(len(m.get("content", "")) for m in messages)
        completion_tokens = len(content)

        return {
            "content": content,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
        }

    # ------------------------------------------------------------------
    # Resolution chain
    # ------------------------------------------------------------------

    def _resolve(
        self,
        prompt_text: str,
        response_schema: type[BaseModel] | None,
    ) -> str:
        # 1. Scripted queue (FIFO)
        if self._scripted:
            return _serialise(self._scripted.popleft())

        # 2. Response map (first key-substring match)
        for key, value in self._response_map.items():
            if key in prompt_text:
                return _serialise(value)

        # 3. Hash fallback
        return self._hash_fallback(prompt_text, response_schema)

    def _hash_fallback(
        self,
        prompt_text: str,
        response_schema: type[BaseModel] | None,
    ) -> str:
        digest = hashlib.sha256(
            f"{self._seed}:{self._call_count}:{prompt_text}".encode()
        ).hexdigest()[:16]

        if response_schema is not None:
            return json.dumps({"_fake": True, "_hash": digest})
        return f"[fake-llm] seed={self._seed} call={self._call_count} hash={digest}"


def _serialise(value: dict[str, Any] | BaseModel | str) -> str:
    """Convert a scripted response value to a JSON/text string."""
    if isinstance(value, str):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return json.dumps(value)
