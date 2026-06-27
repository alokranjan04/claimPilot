"""Azure provider implementations for ClaimPilot infrastructure interfaces.

All classes require ``uv sync --extra azure`` — they raise :exc:`ImportError`
with a helpful message if the SDK is not installed.

Exports:
    AzureOpenAILLMClient    — LLMClient via Azure OpenAI chat completions
    AzureOpenAIEmbedder     — Embedder via Azure OpenAI embeddings
    AzureSearchVectorStore  — VectorStore via Azure AI Search (HNSW)
    AzureSearchReranker     — Reranker via Azure AI Search semantic ranker
    AzureDocumentIntelligenceExtractor — DocExtractor via Document Intelligence
    AzureServiceBusQueue    — Queue via Azure Service Bus
    AzureCosmosCheckpointer — Checkpointer via Azure Cosmos DB
"""

from claimpilot.infra.providers.azure.checkpointer import AzureCosmosCheckpointer
from claimpilot.infra.providers.azure.doc_extractor import (
    AzureDocumentIntelligenceExtractor,
)
from claimpilot.infra.providers.azure.embedder import AzureOpenAIEmbedder
from claimpilot.infra.providers.azure.llm import AzureOpenAILLMClient
from claimpilot.infra.providers.azure.queue import AzureServiceBusQueue
from claimpilot.infra.providers.azure.reranker import AzureSearchReranker
from claimpilot.infra.providers.azure.vector_store import AzureSearchVectorStore

__all__ = [
    "AzureCosmosCheckpointer",
    "AzureDocumentIntelligenceExtractor",
    "AzureOpenAIEmbedder",
    "AzureOpenAILLMClient",
    "AzureSearchReranker",
    "AzureSearchVectorStore",
    "AzureServiceBusQueue",
]
