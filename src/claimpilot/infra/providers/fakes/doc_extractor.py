"""Fake document extractor — returns canned text from binary content."""

from __future__ import annotations

from claimpilot.infra.interfaces import ExtractedDocument


class FakeDocExtractor:
    """Deterministic extractor that decodes bytes as UTF-8 (or returns a placeholder).

    No OCR, no network — useful for offline tests and demos.
    """

    async def extract(self, content: bytes, *, content_type: str) -> ExtractedDocument:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = f"[binary content: {len(content)} bytes, type={content_type}]"

        return ExtractedDocument(
            text=text,
            pages=max(1, len(text) // 3000),  # rough page estimate
            metadata={"content_type": content_type, "provider": "fake"},
        )
