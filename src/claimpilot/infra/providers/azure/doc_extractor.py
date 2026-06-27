"""Azure AI Document Intelligence implementation of
:class:`~claimpilot.infra.interfaces.DocExtractor`.

Uses the ``prebuilt-read`` model to extract text from PDFs, images, and other
document formats.  Entra ID (DefaultAzureCredential) for auth.

Requires: ``uv sync --extra azure``
"""

from __future__ import annotations

from typing import Any

from claimpilot.infra.interfaces import ExtractedDocument


class AzureDocumentIntelligenceExtractor:
    """Extract text from binary documents using Azure AI Document Intelligence.

    The ``prebuilt-read`` model handles PDFs, images (JPEG, PNG, TIFF),
    Office files (DOCX, XLSX, PPTX), and HTML.  Confidence scores are
    averaged across all words and stored in metadata.
    """

    def __init__(self, *, endpoint: str) -> None:
        try:
            from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as exc:
            raise ImportError(
                "Azure provider requires extra dependencies: uv sync --extra azure"
            ) from exc

        # Any justified: azure-ai-documentintelligence SDK uses dynamic attrs.
        self._client: Any = DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential(),
        )

    async def extract(self, content: bytes, *, content_type: str) -> ExtractedDocument:
        """Submit *content* to Document Intelligence and return extracted text."""
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

        poller = await self._client.begin_analyze_document(
            "prebuilt-read",
            AnalyzeDocumentRequest(bytes_source=content),
            content_type=content_type,
        )
        result = await poller.result()

        paragraphs = result.paragraphs or []
        text = "\n".join(p.content for p in paragraphs if p.content)

        pages = result.pages or []
        page_count = max(1, len(pages))

        # Compute average word confidence across all pages.
        all_words = [w for p in pages for w in (p.words or [])]
        avg_confidence: float = (
            sum(w.confidence for w in all_words) / len(all_words) if all_words else 0.0
        )

        return ExtractedDocument(
            text=text,
            pages=page_count,
            metadata={
                "provider": "azure_document_intelligence",
                "avg_confidence": f"{avg_confidence:.4f}",
                "content_type": content_type,
            },
        )
