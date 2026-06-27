"""Interface-conformance tests for the Azure providers.

All Azure SDK calls are mocked via ``sys.modules`` injection so these tests
run without the ``azure`` extra installed (i.e. in the standard CI
environment that only installs ``dev`` dependencies).

Each test group verifies that the Azure provider satisfies the same
protocol contract that the matching fake passes in ``test_infra.py``.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from claimpilot.infra.interfaces import (
    Checkpointer,
    DocExtractor,
    Embedder,
    ExtractedDocument,
    LLMClient,
    Queue,
    QueueMessage,
    Reranker,
    SearchHit,
    VectorRecord,
    VectorStore,
)

# ---------------------------------------------------------------------------
# Shared mock-injection fixture
# ---------------------------------------------------------------------------

# Names of all Azure / OpenAI modules that provider __init__ methods import.
_AZURE_MODULES = [
    "openai",
    "azure",
    "azure.core",
    "azure.core.credentials",
    "azure.identity",
    "azure.identity.aio",
    "azure.search",
    "azure.search.documents",
    "azure.search.documents.aio",
    "azure.search.documents.models",
    "azure.search.documents.indexes",
    "azure.search.documents.indexes.aio",
    "azure.search.documents.indexes.models",
    "azure.ai",
    "azure.ai.documentintelligence",
    "azure.ai.documentintelligence.aio",
    "azure.ai.documentintelligence.models",
    "azure.servicebus",
    "azure.servicebus.aio",
    "azure.cosmos",
    "azure.cosmos.aio",
    "azure.cosmos.exceptions",
    "azure.monitor",
    "azure.monitor.opentelemetry",
    "opentelemetry",
    "opentelemetry.trace",
]


class _AsyncSearchResults:
    """Mock async iterable for Azure Search results."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def __aiter__(self) -> _AsyncSearchResults:
        self._iter = iter(self._docs)
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None


@pytest.fixture(autouse=True)
def _inject_azure_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject stub modules into sys.modules for every test in this file.

    monkeypatch restores the original sys.modules state after each test.
    """
    for name in _AZURE_MODULES:
        if name not in sys.modules:
            monkeypatch.setitem(sys.modules, name, MagicMock())


# ---------------------------------------------------------------------------
# Helper — force-reload a provider module so it picks up the fresh mocks.
# (Provider modules cache nothing at import time; __init__ does the lazy
# imports.  So we just need to ensure our sys.modules stubs are in place
# before instantiation, which the autouse fixture above guarantees.)
# ---------------------------------------------------------------------------


def _openai_client_mock(content: str = '{"decision":"covered"}') -> MagicMock:
    """Return a mock AsyncAzureOpenAI client whose completions return *content*."""
    mock_client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.usage = MagicMock()
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 20
    mock_client.chat.completions.create = AsyncMock(return_value=response)

    embed_response = MagicMock()
    embed_response.data = [MagicMock()]
    embed_response.data[0].index = 0
    embed_response.data[0].embedding = [0.1, 0.2, 0.3]
    mock_client.embeddings.create = AsyncMock(return_value=embed_response)
    return mock_client


# ---------------------------------------------------------------------------
# LLMClient — AzureOpenAILLMClient
# ---------------------------------------------------------------------------


class TestAzureOpenAILLMClient:
    """Protocol conformance + behaviour tests for AzureOpenAILLMClient."""

    def _make_client(self, content: str = '{"decision":"covered"}') -> Any:
        mock_openai_client = _openai_client_mock(content)

        sys.modules["openai"].AsyncAzureOpenAI = MagicMock(  # type: ignore[attr-defined]
            return_value=mock_openai_client
        )
        sys.modules["azure.identity.aio"].DefaultAzureCredential = MagicMock()  # type: ignore[attr-defined]
        sys.modules["azure.identity.aio"].get_bearer_token_provider = MagicMock(  # type: ignore[attr-defined]
            return_value="token_provider"
        )

        from claimpilot.infra.providers.azure.llm import AzureOpenAILLMClient

        return AzureOpenAILLMClient(
            endpoint="https://fake.openai.azure.com",
            deployment="gpt-4o",
        )

    def test_satisfies_protocol(self) -> None:
        client = self._make_client()
        assert isinstance(client, LLMClient)

    async def test_generate_returns_content_and_usage(self) -> None:
        client = self._make_client()
        result = await client.generate([{"role": "user", "content": "hello"}])
        assert "content" in result
        assert "usage" in result
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 20

    async def test_generate_with_response_schema(self) -> None:
        """response_schema triggers json_object response_format."""
        from pydantic import BaseModel

        class Dummy(BaseModel):
            decision: str = "covered"

        client = self._make_client('{"decision":"covered"}')
        result = await client.generate(
            [{"role": "user", "content": "assess"}],
            response_schema=Dummy,
        )
        assert "content" in result
        # json_object mode: content must be valid JSON.
        parsed = json.loads(result["content"])
        assert parsed["decision"] == "covered"

    async def test_invalid_json_in_structured_mode_is_handled(self) -> None:
        client = self._make_client("not valid json")
        from pydantic import BaseModel

        class Schema(BaseModel):
            x: int = 0

        result = await client.generate([{"role": "user", "content": "q"}], response_schema=Schema)
        # _parse_error key is injected on bad JSON.
        parsed = json.loads(result["content"])
        assert parsed.get("_parse_error") is True


# ---------------------------------------------------------------------------
# Embedder — AzureOpenAIEmbedder
# ---------------------------------------------------------------------------


class TestAzureOpenAIEmbedder:
    def _make_embedder(self, vectors: list[list[float]] | None = None) -> Any:
        vectors = vectors or [[0.1, 0.2, 0.3]]
        mock_client = MagicMock()
        embed_response = MagicMock()
        embed_response.data = [MagicMock(index=i, embedding=v) for i, v in enumerate(vectors)]
        mock_client.embeddings.create = AsyncMock(return_value=embed_response)

        sys.modules["openai"].AsyncAzureOpenAI = MagicMock(return_value=mock_client)  # type: ignore[attr-defined]
        sys.modules["azure.identity.aio"].DefaultAzureCredential = MagicMock()  # type: ignore[attr-defined]
        sys.modules["azure.identity.aio"].get_bearer_token_provider = MagicMock(  # type: ignore[attr-defined]
            return_value="tok"
        )

        from claimpilot.infra.providers.azure.embedder import AzureOpenAIEmbedder

        return AzureOpenAIEmbedder(
            endpoint="https://fake.openai.azure.com",
            deployment="text-embedding-3-small",
            dims=3,
        )

    def test_satisfies_protocol(self) -> None:
        emb = self._make_embedder()
        assert isinstance(emb, Embedder)

    def test_dimensions_property(self) -> None:
        emb = self._make_embedder()
        assert emb.dimensions == 3

    async def test_embed_returns_vectors(self) -> None:
        emb = self._make_embedder([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        result = await emb.embed(["hello", "world"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]

    async def test_embed_empty(self) -> None:
        emb = self._make_embedder()
        result = await emb.embed([])
        assert result == []


# ---------------------------------------------------------------------------
# VectorStore — AzureSearchVectorStore
# ---------------------------------------------------------------------------


class TestAzureSearchVectorStore:
    def _make_store(self) -> Any:
        mock_client = MagicMock()
        mock_client.upload_documents = AsyncMock(return_value=None)
        mock_client.delete_documents = AsyncMock(return_value=None)

        # search returns an awaitable that resolves to an async iterable
        search_results = _AsyncSearchResults(
            [
                {
                    "id": "chunk-1",
                    "text": "policy text",
                    "@search.score": 0.95,
                    "metadata": json.dumps({"doc_id": "p1"}),
                }
            ]
        )
        mock_client.search = AsyncMock(return_value=search_results)

        sys.modules["azure.identity.aio"].DefaultAzureCredential = MagicMock()  # type: ignore[attr-defined]
        sys.modules["azure.core.credentials"].AzureKeyCredential = MagicMock()  # type: ignore[attr-defined]
        sys.modules["azure.search.documents.aio"].SearchClient = MagicMock(  # type: ignore[attr-defined]
            return_value=mock_client
        )
        sys.modules["azure.search.documents.models"].VectorizedQuery = MagicMock()  # type: ignore[attr-defined]

        # Mock the index client for _ensure_index
        mock_index_client = MagicMock()
        mock_index_client.get_index = AsyncMock(return_value=MagicMock())  # index exists
        sys.modules["azure.search.documents.indexes.aio"].SearchIndexClient = MagicMock(  # type: ignore[attr-defined]
            return_value=mock_index_client
        )

        from claimpilot.infra.providers.azure.vector_store import AzureSearchVectorStore

        return AzureSearchVectorStore(
            endpoint="https://fake.search.windows.net",
            index_name="claimpilot-chunks",
        )

    def test_satisfies_protocol(self) -> None:
        store = self._make_store()
        assert isinstance(store, VectorStore)

    async def test_upsert_calls_upload(self) -> None:
        store = self._make_store()
        records = [VectorRecord(id="r1", text="hello", embedding=[0.1, 0.2])]
        await store.upsert(records)
        store._client.upload_documents.assert_called_once()

    async def test_search_returns_hits(self) -> None:
        store = self._make_store()
        hits = await store.search([0.1, 0.2], top_k=5)
        assert len(hits) == 1
        assert isinstance(hits[0], SearchHit)
        assert hits[0].id == "chunk-1"
        assert hits[0].metadata["doc_id"] == "p1"

    async def test_upsert_empty_is_noop(self) -> None:
        store = self._make_store()
        await store.upsert([])
        store._client.upload_documents.assert_not_called()

    async def test_delete_calls_delete_documents(self) -> None:
        store = self._make_store()
        await store.delete(["chunk-1"])
        store._client.delete_documents.assert_called_once()

    async def test_delete_empty_is_noop(self) -> None:
        store = self._make_store()
        await store.delete([])
        store._client.delete_documents.assert_not_called()


# ---------------------------------------------------------------------------
# Reranker — AzureSearchReranker
# ---------------------------------------------------------------------------


class TestAzureSearchReranker:
    def _make_reranker(self) -> Any:
        mock_client = MagicMock()

        search_results = _AsyncSearchResults(
            [
                {
                    "id": "chunk-1",
                    "text": "reranked text",
                    "@search.reranker_score": 2.5,
                    "metadata": "{}",
                }
            ]
        )
        mock_client.search = AsyncMock(return_value=search_results)

        sys.modules["azure.identity.aio"].DefaultAzureCredential = MagicMock()  # type: ignore[attr-defined]
        sys.modules["azure.core.credentials"].AzureKeyCredential = MagicMock()  # type: ignore[attr-defined]
        sys.modules["azure.search.documents.aio"].SearchClient = MagicMock(  # type: ignore[attr-defined]
            return_value=mock_client
        )

        from claimpilot.infra.providers.azure.reranker import AzureSearchReranker

        return AzureSearchReranker(
            endpoint="https://fake.search.windows.net",
            index_name="claimpilot-chunks",
        )

    def test_satisfies_protocol(self) -> None:
        rr = self._make_reranker()
        assert isinstance(rr, Reranker)

    async def test_rerank_returns_hits(self) -> None:
        rr = self._make_reranker()
        hits = [SearchHit(id="chunk-1", text="policy text", score=0.9)]
        result = await rr.rerank("water damage", hits, top_k=5)
        assert len(result) == 1
        assert result[0].score == 2.5

    async def test_rerank_empty_returns_empty(self) -> None:
        rr = self._make_reranker()
        result = await rr.rerank("query", [], top_k=5)
        assert result == []


# ---------------------------------------------------------------------------
# DocExtractor — AzureDocumentIntelligenceExtractor
# ---------------------------------------------------------------------------


class TestAzureDocumentIntelligenceExtractor:
    def _make_extractor(self) -> Any:
        # Build a mock analyze result with pages + paragraphs.
        word = MagicMock()
        word.confidence = 0.98
        page = MagicMock()
        page.words = [word]

        para = MagicMock()
        para.content = "This is extracted text."

        analyze_result = MagicMock()
        analyze_result.pages = [page]
        analyze_result.paragraphs = [para]

        poller = AsyncMock()
        poller.result = AsyncMock(return_value=analyze_result)

        mock_client = MagicMock()
        mock_client.begin_analyze_document = AsyncMock(return_value=poller)

        sys.modules["azure.identity.aio"].DefaultAzureCredential = MagicMock()  # type: ignore[attr-defined]
        sys.modules["azure.ai.documentintelligence.aio"].DocumentIntelligenceClient = MagicMock(  # type: ignore[attr-defined]
            return_value=mock_client
        )
        sys.modules["azure.ai.documentintelligence.models"].AnalyzeDocumentRequest = MagicMock()  # type: ignore[attr-defined]

        from claimpilot.infra.providers.azure.doc_extractor import (
            AzureDocumentIntelligenceExtractor,
        )

        return AzureDocumentIntelligenceExtractor(
            endpoint="https://fake.cognitiveservices.azure.com"
        )

    def test_satisfies_protocol(self) -> None:
        ext = self._make_extractor()
        assert isinstance(ext, DocExtractor)

    async def test_extract_returns_document(self) -> None:
        ext = self._make_extractor()
        doc = await ext.extract(b"%PDF-1.4...", content_type="application/pdf")
        assert isinstance(doc, ExtractedDocument)
        assert "extracted text" in doc.text
        assert doc.pages >= 1
        assert doc.metadata["provider"] == "azure_document_intelligence"

    async def test_extract_confidence_in_metadata(self) -> None:
        ext = self._make_extractor()
        doc = await ext.extract(b"content", content_type="text/plain")
        assert "avg_confidence" in doc.metadata
        assert float(doc.metadata["avg_confidence"]) == pytest.approx(0.98, abs=1e-3)


# ---------------------------------------------------------------------------
# Queue — AzureServiceBusQueue
# ---------------------------------------------------------------------------


class TestAzureServiceBusQueue:
    def _make_queue(self) -> Any:
        # Mock a received message.
        sb_msg = MagicMock()
        sb_msg.body = iter([json.dumps({"claim_id": "C001"}).encode()])
        sb_msg.message_id = "msg-001"

        receiver_mock = MagicMock()
        receiver_mock.receive_messages = AsyncMock(return_value=[sb_msg])
        receiver_mock.complete_message = AsyncMock(return_value=None)
        receiver_mock.__aenter__ = AsyncMock(return_value=receiver_mock)
        receiver_mock.__aexit__ = AsyncMock(return_value=None)

        sender_mock = MagicMock()
        sender_mock.send_messages = AsyncMock(return_value=None)
        sender_mock.__aenter__ = AsyncMock(return_value=sender_mock)
        sender_mock.__aexit__ = AsyncMock(return_value=None)

        sb_client_mock = MagicMock()
        sb_client_mock.get_queue_sender = MagicMock(return_value=sender_mock)
        sb_client_mock.get_queue_receiver = MagicMock(return_value=receiver_mock)

        sys.modules["azure.identity.aio"].DefaultAzureCredential = MagicMock()  # type: ignore[attr-defined]
        sys.modules["azure.servicebus.aio"].ServiceBusClient = MagicMock(  # type: ignore[attr-defined]
            return_value=sb_client_mock
        )
        sys.modules["azure.servicebus"].ServiceBusMessage = MagicMock()  # type: ignore[attr-defined]

        from claimpilot.infra.providers.azure.queue import AzureServiceBusQueue

        return AzureServiceBusQueue(
            namespace="fake.servicebus.windows.net",
            queue_name="claims",
        )

    def test_satisfies_protocol(self) -> None:
        q = self._make_queue()
        assert isinstance(q, Queue)

    async def test_enqueue(self) -> None:
        q = self._make_queue()
        msg = QueueMessage(id="m1", body={"claim_id": "C001"})
        await q.enqueue(msg)
        q._sb_client.get_queue_sender.assert_called_once_with(queue_name="claims")

    async def test_dequeue_returns_message(self) -> None:
        q = self._make_queue()
        msg = await q.dequeue(timeout_seconds=1.0)
        assert msg is not None
        assert msg.id == "msg-001"
        assert msg.body["claim_id"] == "C001"

    async def test_ack_completes_message(self) -> None:
        q = self._make_queue()
        msg = await q.dequeue(timeout_seconds=1.0)
        assert msg is not None
        await q.ack(msg.id)
        q._receiver.complete_message.assert_called_once()

    async def test_ack_unknown_id_is_noop(self) -> None:
        q = self._make_queue()
        await q.ack("nonexistent")  # must not raise

    async def test_dequeue_empty_returns_none(self) -> None:
        q = self._make_queue()
        # Override receiver to return empty list.
        q._receiver = MagicMock()
        q._receiver.receive_messages = AsyncMock(return_value=[])
        result = await q.dequeue(timeout_seconds=0.1)
        assert result is None


# ---------------------------------------------------------------------------
# Checkpointer — AzureCosmosCheckpointer
# ---------------------------------------------------------------------------


class TestAzureCosmosCheckpointer:
    def _make_checkpointer(self, stored: dict[str, Any] | None = None) -> Any:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError  # noqa: F401

        # Set up fake CosmosResourceNotFoundError in sys.modules.
        cosmos_exc_mock = MagicMock()
        cosmos_exc_mock.CosmosResourceNotFoundError = Exception
        sys.modules["azure.cosmos.exceptions"] = cosmos_exc_mock  # type: ignore[assignment]

        container_mock = MagicMock()
        container_mock.upsert_item = AsyncMock(return_value=None)
        container_mock.delete_item = AsyncMock(return_value=None)

        if stored is not None:

            async def _read_item(*args: Any, **kwargs: Any) -> dict[str, Any]:
                return {"id": kwargs.get("item", ""), "state": stored}

            container_mock.read_item = AsyncMock(side_effect=_read_item)
        else:
            container_mock.read_item = AsyncMock(
                side_effect=cosmos_exc_mock.CosmosResourceNotFoundError("not found")
            )

        db_mock = MagicMock()
        db_mock.get_container_client = MagicMock(return_value=container_mock)

        cosmos_client_mock = MagicMock()
        cosmos_client_mock.get_database_client = MagicMock(return_value=db_mock)

        sys.modules["azure.identity.aio"].DefaultAzureCredential = MagicMock()  # type: ignore[attr-defined]
        sys.modules["azure.cosmos.aio"].CosmosClient = MagicMock(  # type: ignore[attr-defined]
            return_value=cosmos_client_mock
        )

        from claimpilot.infra.providers.azure.checkpointer import AzureCosmosCheckpointer

        return AzureCosmosCheckpointer(
            endpoint="https://fake.documents.azure.com:443",
            database="claimpilot",
            container="checkpoints",
        )

    def test_satisfies_protocol(self) -> None:
        cp = self._make_checkpointer()
        assert isinstance(cp, Checkpointer)

    async def test_save(self) -> None:
        cp = self._make_checkpointer()
        await cp.save("claim-1", {"status": "in_progress"})
        container = await cp._get_container()
        container.upsert_item.assert_called_once_with(
            {"id": "claim-1", "state": {"status": "in_progress"}}
        )

    async def test_load_existing(self) -> None:
        cp = self._make_checkpointer(stored={"status": "done"})
        state = await cp.load("claim-1")
        assert state == {"status": "done"}

    async def test_load_missing_returns_none(self) -> None:
        cp = self._make_checkpointer(stored=None)
        state = await cp.load("missing")
        assert state is None

    async def test_delete(self) -> None:
        cp = self._make_checkpointer()
        await cp.delete("claim-1")
        container = await cp._get_container()
        container.delete_item.assert_called_once_with(item="claim-1", partition_key="claim-1")

    async def test_delete_missing_is_noop(self) -> None:
        """delete of a non-existent key must not raise."""
        cosmos_exc_mock = sys.modules["azure.cosmos.exceptions"]
        cosmos_exc_mock.CosmosResourceNotFoundError = Exception

        cp = self._make_checkpointer()
        container = await cp._get_container()
        container.delete_item = AsyncMock(
            side_effect=cosmos_exc_mock.CosmosResourceNotFoundError("gone")
        )
        await cp.delete("nonexistent")  # must not raise


# ---------------------------------------------------------------------------
# Azure Monitor Span Exporter
# ---------------------------------------------------------------------------


class TestAzureMonitorSpanExporter:
    def _make_exporter(self) -> Any:
        tracer_mock = MagicMock()
        span_ctx_mock = MagicMock()
        span_ctx_mock.__enter__ = MagicMock(return_value=MagicMock())
        span_ctx_mock.__exit__ = MagicMock(return_value=False)
        tracer_mock.start_as_current_span = MagicMock(return_value=span_ctx_mock)

        trace_mock = MagicMock()
        trace_mock.get_tracer = MagicMock(return_value=tracer_mock)
        trace_mock.get_tracer_provider = MagicMock(return_value=MagicMock())

        sys.modules["opentelemetry"] = MagicMock()  # type: ignore[assignment]
        sys.modules["opentelemetry.trace"] = trace_mock  # type: ignore[assignment]
        sys.modules["azure.monitor"] = MagicMock()  # type: ignore[assignment]
        sys.modules["azure.monitor.opentelemetry"] = MagicMock()  # type: ignore[assignment]
        sys.modules["azure.monitor.opentelemetry"].configure_azure_monitor = MagicMock()

        from claimpilot.observability.azure_exporter import AzureMonitorSpanExporter

        return AzureMonitorSpanExporter(connection_string="InstrumentationKey=fake")

    def test_satisfies_span_exporter_protocol(self) -> None:
        from claimpilot.observability.tracer import SpanExporter

        exp = self._make_exporter()
        assert isinstance(exp, SpanExporter)

    def test_export_ok_span(self) -> None:
        from claimpilot.observability.tracer import SpanData

        exp = self._make_exporter()
        span = SpanData(name="intake", claim_id="C001", duration_ms=5.0)
        exp.export(span)
        exp._tracer.start_as_current_span.assert_called_once()

    def test_export_error_span(self) -> None:
        from claimpilot.observability.tracer import SpanData

        # Set up Status/StatusCode mocks in opentelemetry.trace.
        sys.modules["opentelemetry.trace"].Status = MagicMock()
        sys.modules["opentelemetry.trace"].StatusCode = MagicMock()
        sys.modules["opentelemetry.trace"].StatusCode.ERROR = "ERROR"

        exp = self._make_exporter()
        span = SpanData(
            name="fraud_risk",
            claim_id="C002",
            duration_ms=3.0,
            status_ok=False,
            error_message="fraud agent failed",
        )
        exp.export(span)
        exp._tracer.start_as_current_span.assert_called_once()
