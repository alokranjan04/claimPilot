"""Interface-conformance tests for the fake providers.

Each test group verifies that the fake implementation satisfies the
protocol defined in ``claimpilot.infra.interfaces`` and behaves
correctly for the basic operations.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from claimpilot.infra.di import ProviderSet, create_providers
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
from claimpilot.infra.providers.fakes import (
    FakeCheckpointer,
    FakeDocExtractor,
    FakeEmbedder,
    FakeLLMClient,
    FakeQueue,
    FakeReranker,
    FakeVectorStore,
)
from claimpilot.infra.settings import Settings

# ── Protocol conformance ─────────────────────────────────────────────────


class TestProtocolConformance:
    """Verify every fake is a runtime-checkable instance of its protocol."""

    def test_llm_client(self) -> None:
        assert isinstance(FakeLLMClient(), LLMClient)

    def test_embedder(self) -> None:
        assert isinstance(FakeEmbedder(), Embedder)

    def test_vector_store(self) -> None:
        assert isinstance(FakeVectorStore(), VectorStore)

    def test_doc_extractor(self) -> None:
        assert isinstance(FakeDocExtractor(), DocExtractor)

    def test_queue(self) -> None:
        assert isinstance(FakeQueue(), Queue)

    def test_checkpointer(self) -> None:
        assert isinstance(FakeCheckpointer(), Checkpointer)

    def test_reranker(self) -> None:
        assert isinstance(FakeReranker(), Reranker)


# ── LLMClient ────────────────────────────────────────────────────────────


class TestFakeLLMClient:
    async def test_generate_returns_content_and_usage(self) -> None:
        llm = FakeLLMClient(seed=1)
        result = await llm.generate([{"role": "user", "content": "hello"}])
        assert "content" in result
        assert "usage" in result
        assert "prompt_tokens" in result["usage"]
        assert "completion_tokens" in result["usage"]

    async def test_deterministic_across_instances(self) -> None:
        """Same seed + same input → same output."""
        a = await FakeLLMClient(seed=7).generate([{"role": "user", "content": "test"}])
        b = await FakeLLMClient(seed=7).generate([{"role": "user", "content": "test"}])
        assert a["content"] == b["content"]

    async def test_different_seeds_differ(self) -> None:
        a = await FakeLLMClient(seed=1).generate([{"role": "user", "content": "x"}])
        b = await FakeLLMClient(seed=2).generate([{"role": "user", "content": "x"}])
        assert a["content"] != b["content"]

    async def test_structured_output_returns_json(self) -> None:
        class Dummy(BaseModel):
            value: int = 0

        llm = FakeLLMClient()
        result = await llm.generate(
            [{"role": "user", "content": "hi"}],
            response_schema=Dummy,
        )
        parsed = json.loads(result["content"])
        assert "_fake" in parsed


class TestFakeLLMClientScripted:
    """Tests for the scripted-response and response-map features."""

    async def test_scripted_queue_fifo(self) -> None:
        llm = FakeLLMClient(scripted=["first", "second"])
        r1 = await llm.generate([{"role": "user", "content": "a"}])
        r2 = await llm.generate([{"role": "user", "content": "b"}])
        assert r1["content"] == "first"
        assert r2["content"] == "second"

    async def test_scripted_exhausted_falls_to_hash(self) -> None:
        llm = FakeLLMClient(scripted=["only"])
        r1 = await llm.generate([{"role": "user", "content": "a"}])
        assert r1["content"] == "only"
        # Second call falls through to hash
        r2 = await llm.generate([{"role": "user", "content": "a"}])
        assert "[fake-llm]" in r2["content"]

    async def test_scripted_dict_serialised_as_json(self) -> None:
        llm = FakeLLMClient(scripted=[{"decision": "covered", "confidence": 0.95}])
        r = await llm.generate([{"role": "user", "content": "assess"}])
        parsed = json.loads(r["content"])
        assert parsed["decision"] == "covered"
        assert parsed["confidence"] == 0.95

    async def test_scripted_pydantic_model(self) -> None:
        class FakeOpinion(BaseModel):
            decision: str = "denied"
            confidence: float = 0.1

        llm = FakeLLMClient(scripted=[FakeOpinion()])
        r = await llm.generate([{"role": "user", "content": "assess"}])
        parsed = json.loads(r["content"])
        assert parsed["decision"] == "denied"

    async def test_response_map_matches_substring(self) -> None:
        llm = FakeLLMClient(
            response_map={
                "coverage": {"decision": "covered"},
                "fraud": {"score": 0.8},
            }
        )
        r = await llm.generate([{"role": "user", "content": "assess coverage"}])
        parsed = json.loads(r["content"])
        assert parsed["decision"] == "covered"

    async def test_response_map_no_match_falls_to_hash(self) -> None:
        llm = FakeLLMClient(response_map={"coverage": "matched"})
        r = await llm.generate([{"role": "user", "content": "something else"}])
        assert "[fake-llm]" in r["content"]

    async def test_scripted_takes_priority_over_map(self) -> None:
        llm = FakeLLMClient(
            scripted=["from-script"],
            response_map={"hello": "from-map"},
        )
        r = await llm.generate([{"role": "user", "content": "hello"}])
        assert r["content"] == "from-script"
        # After script exhausted, map kicks in
        r2 = await llm.generate([{"role": "user", "content": "hello"}])
        assert r2["content"] == "from-map"


# ── Embedder ─────────────────────────────────────────────────────────────


class TestFakeEmbedder:
    async def test_embed_returns_correct_dimensions(self) -> None:
        emb = FakeEmbedder(dims=32)
        vectors = await emb.embed(["hello", "world"])
        assert len(vectors) == 2
        assert all(len(v) == 32 for v in vectors)

    async def test_dimensions_property(self) -> None:
        emb = FakeEmbedder(dims=128)
        assert emb.dimensions == 128

    async def test_deterministic(self) -> None:
        a = await FakeEmbedder(seed=5).embed(["foo"])
        b = await FakeEmbedder(seed=5).embed(["foo"])
        assert a == b

    async def test_different_texts_differ(self) -> None:
        emb = FakeEmbedder()
        vecs = await emb.embed(["alpha", "beta"])
        assert vecs[0] != vecs[1]

    async def test_unit_normalised(self) -> None:
        emb = FakeEmbedder(dims=64)
        [vec] = await emb.embed(["normalise me"])
        norm = sum(x * x for x in vec) ** 0.5
        assert abs(norm - 1.0) < 1e-6


# ── VectorStore ──────────────────────────────────────────────────────────


class TestFakeVectorStore:
    async def test_upsert_and_search(self) -> None:
        store = FakeVectorStore()
        emb = FakeEmbedder(dims=16)
        [v1] = await emb.embed(["insurance policy"])
        [v2] = await emb.embed(["pizza recipe"])

        await store.upsert(
            [
                VectorRecord(
                    id="1",
                    text="insurance policy",
                    embedding=v1,
                    metadata={"type": "policy"},
                ),
                VectorRecord(
                    id="2",
                    text="pizza recipe",
                    embedding=v2,
                    metadata={"type": "food"},
                ),
            ]
        )

        results = await store.search(v1, top_k=2)
        assert len(results) == 2
        assert isinstance(results[0], SearchHit)
        # The insurance vector should be most similar to itself.
        assert results[0].id == "1"

    async def test_search_with_metadata_filter(self) -> None:
        store = FakeVectorStore()
        emb = FakeEmbedder(dims=8)
        [v] = await emb.embed(["shared"])

        await store.upsert(
            [
                VectorRecord(id="a", text="a", embedding=v, metadata={"ns": "x"}),
                VectorRecord(id="b", text="b", embedding=v, metadata={"ns": "y"}),
            ]
        )
        results = await store.search(v, top_k=10, filter_metadata={"ns": "y"})
        assert len(results) == 1
        assert results[0].id == "b"

    async def test_delete(self) -> None:
        store = FakeVectorStore()
        emb = FakeEmbedder(dims=8)
        [v] = await emb.embed(["del"])

        await store.upsert([VectorRecord(id="z", text="z", embedding=v)])
        await store.delete(["z"])
        results = await store.search(v, top_k=5)
        assert len(results) == 0

    async def test_upsert_overwrites(self) -> None:
        store = FakeVectorStore()
        emb = FakeEmbedder(dims=8)
        [v] = await emb.embed(["dup"])

        await store.upsert([VectorRecord(id="dup", text="original", embedding=v)])
        await store.upsert([VectorRecord(id="dup", text="updated", embedding=v)])
        results = await store.search(v, top_k=1)
        assert results[0].text == "updated"


# ── Reranker ─────────────────────────────────────────────────────────────


class TestFakeReranker:
    async def test_identity_passthrough(self) -> None:
        hits = [
            SearchHit(id="a", text="first", score=0.9),
            SearchHit(id="b", text="second", score=0.5),
        ]
        rr = FakeReranker()
        result = await rr.rerank("query", hits, top_k=10)
        assert result == hits

    async def test_truncates_to_top_k(self) -> None:
        hits = [SearchHit(id=str(i), text=f"hit-{i}", score=0.5) for i in range(10)]
        rr = FakeReranker()
        result = await rr.rerank("query", hits, top_k=3)
        assert len(result) == 3
        assert [h.id for h in result] == ["0", "1", "2"]

    async def test_empty_hits(self) -> None:
        rr = FakeReranker()
        result = await rr.rerank("query", [], top_k=5)
        assert result == []


# ── DocExtractor ─────────────────────────────────────────────────────────


class TestFakeDocExtractor:
    async def test_extract_utf8(self) -> None:
        ext = FakeDocExtractor()
        doc = await ext.extract(b"hello world", content_type="text/plain")
        assert isinstance(doc, ExtractedDocument)
        assert doc.text == "hello world"
        assert doc.pages >= 1

    async def test_extract_binary_fallback(self) -> None:
        ext = FakeDocExtractor()
        doc = await ext.extract(b"\xff\xfe", content_type="application/pdf")
        assert "binary content" in doc.text


# ── Queue ────────────────────────────────────────────────────────────────


class TestFakeQueue:
    async def test_enqueue_dequeue(self) -> None:
        q = FakeQueue()
        msg = QueueMessage(id="m1", body={"claim_id": "C001"})
        await q.enqueue(msg)
        got = await q.dequeue(timeout_seconds=1.0)
        assert got is not None
        assert got.id == "m1"
        assert got.body["claim_id"] == "C001"

    async def test_dequeue_timeout_returns_none(self) -> None:
        q = FakeQueue()
        got = await q.dequeue(timeout_seconds=0.05)
        assert got is None

    async def test_ack(self) -> None:
        q = FakeQueue()
        await q.enqueue(QueueMessage(id="m2", body={}))
        got = await q.dequeue(timeout_seconds=1.0)
        assert got is not None
        await q.ack(got.id)
        # Ack of unknown ID is a no-op.
        await q.ack("nonexistent")

    async def test_fifo_ordering(self) -> None:
        q = FakeQueue()
        for i in range(3):
            await q.enqueue(QueueMessage(id=f"q{i}", body={"i": i}))
        ids = []
        for _ in range(3):
            msg = await q.dequeue(timeout_seconds=1.0)
            assert msg is not None
            ids.append(msg.id)
        assert ids == ["q0", "q1", "q2"]


# ── Checkpointer ────────────────────────────────────────────────────────


class TestFakeCheckpointer:
    async def test_save_load(self) -> None:
        cp = FakeCheckpointer()
        await cp.save("c1", {"status": "in_progress"})
        state = await cp.load("c1")
        assert state == {"status": "in_progress"}

    async def test_load_missing_returns_none(self) -> None:
        cp = FakeCheckpointer()
        assert await cp.load("missing") is None

    async def test_delete(self) -> None:
        cp = FakeCheckpointer()
        await cp.save("c2", {"a": 1})
        await cp.delete("c2")
        assert await cp.load("c2") is None

    async def test_isolation_on_save(self) -> None:
        """Mutations to the original dict after save must not affect stored data."""
        cp = FakeCheckpointer()
        data: dict[str, object] = {"key": "original"}
        await cp.save("c3", data)
        data["key"] = "mutated"
        loaded = await cp.load("c3")
        assert loaded is not None
        assert loaded["key"] == "original"

    async def test_isolation_on_load(self) -> None:
        """Mutations to a loaded dict must not affect stored data."""
        cp = FakeCheckpointer()
        await cp.save("c4", {"key": "original"})
        loaded = await cp.load("c4")
        assert loaded is not None
        loaded["key"] = "mutated"
        reloaded = await cp.load("c4")
        assert reloaded is not None
        assert reloaded["key"] == "original"

    async def test_overwrite(self) -> None:
        cp = FakeCheckpointer()
        await cp.save("c5", {"v": 1})
        await cp.save("c5", {"v": 2})
        loaded = await cp.load("c5")
        assert loaded == {"v": 2}


# ── DI factory ───────────────────────────────────────────────────────────


class TestDI:
    def test_default_returns_fakes(self) -> None:
        ps = create_providers()
        assert isinstance(ps, ProviderSet)
        assert isinstance(ps.llm, LLMClient)
        assert isinstance(ps.embedder, Embedder)
        assert isinstance(ps.vector_store, VectorStore)
        assert isinstance(ps.doc_extractor, DocExtractor)
        assert isinstance(ps.queue, Queue)
        assert isinstance(ps.checkpointer, Checkpointer)
        assert isinstance(ps.reranker, Reranker)

    def test_explicit_fake_settings(self) -> None:
        ps = create_providers(Settings(provider="fake"))
        assert isinstance(ps.llm, LLMClient)

    def test_azure_provider_wires_without_error(self) -> None:
        """PROVIDER=azure creates providers when the azure extra is installed."""
        # This test validates that the DI factory can instantiate Azure providers.
        # If azure extra is not installed, it raises ImportError; if installed,
        # providers are created (they may fail to connect, but instantiation works).
        try:
            ps = create_providers(Settings(provider="azure"))  # type: ignore[arg-type]
            assert isinstance(ps, ProviderSet)
        except ImportError:
            pytest.skip("azure extra not installed")


# ── Settings ─────────────────────────────────────────────────────────────


class TestSettings:
    def test_defaults(self) -> None:
        s = Settings()
        assert s.provider == "fake"
        assert s.fake_seed == 42
        assert s.threshold_coverage_confidence == 0.8

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVIDER", "fake")
        monkeypatch.setenv("FAKE_SEED", "99")
        s = Settings()
        assert s.provider == "fake"
        assert s.fake_seed == 99
