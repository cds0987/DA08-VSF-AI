import pytest

from haystack_interface import IngestInput, OfflineProvider, build_engine
from haystack_interface.config import HaystackSettings
from haystack_interface.engine import HaystackRagEngine


class StubEmbedder:
    async def embed(self, text: str):
        return [0.1]

    async def embed_batch(self, texts):
        return [[0.1] for _ in texts]


class StubReranker:
    async def rerank(self, query, results, top_k, threshold):
        return results[:top_k]


class RecordingVectors:
    def __init__(self):
        self.calls = []

    async def upsert(self, chunk_id, vector, payload):
        raise AssertionError("engine should use upsert_many for ingest rewrite")

    async def upsert_many(self, records):
        self.calls.append(("upsert_many", [record.chunk_id for record in records]))

    async def hybrid_search(self, vector, query_text, top_k=20):
        return []

    async def list_chunk_ids_by_document(self, document_id):
        self.calls.append(("list_chunk_ids_by_document", document_id))
        return ["doc-order::p0::c0", "doc-order::stale"]

    async def delete_many(self, chunk_ids):
        self.calls.append(("delete_many", list(chunk_ids)))

    async def delete_by_document(self, document_id):
        self.calls.append(("delete_by_document", document_id))


@pytest.mark.asyncio
async def test_engine_search_returns_contract_fields() -> None:
    engine = build_engine(provider=OfflineProvider(256), caption=True)
    await engine.ingest(
        IngestInput(
            document_id="doc-1",
            document_name="Account Guide",
            file_type="md",
            markdown="# Reset mật khẩu\nVào Cài đặt > Bảo mật để đặt lại mật khẩu.\n",
        )
    )

    results = await engine.search("reset mật khẩu", correlation_id="cid-001", rerank_threshold=0.0)

    assert results
    top = results[0]
    assert top.correlation_id == "cid-001"
    assert top.unit_id.startswith("doc-1::p0::c")
    assert top.display_name == "Account Guide"
    assert top.caption
    assert top.content
    assert top.heading_path == ["Reset mật khẩu"]
    assert top.lineage.source_uri == "local://doc-1"
    assert top.lineage.artifact_uri == "local://doc-1#artifact"


@pytest.mark.asyncio
async def test_engine_search_generates_correlation_id_when_missing() -> None:
    engine = build_engine(provider=OfflineProvider(256), caption=False)
    await engine.ingest(
        IngestInput(
            document_id="doc-2",
            document_name="HR Guide",
            file_type="md",
            markdown="# Leave\nQuy trình nghỉ phép năm.\n",
        )
    )

    results = await engine.search("nghỉ phép", rerank_threshold=0.0)

    assert results
    assert results[0].correlation_id


@pytest.mark.asyncio
async def test_reingest_shorter_document_prunes_stale_chunks() -> None:
    engine = build_engine(provider=OfflineProvider(256), caption=False)
    await engine.ingest(
        IngestInput(
            document_id="doc-prune",
            document_name="Prune Guide",
            file_type="md",
            markdown="# Title\n" + "word " * 260,
        )
    )

    before = await engine.search("word", rerank_threshold=0.0, top_k=10)
    before_count = len([r for r in before if r.document_id == "doc-prune"])

    await engine.ingest(
        IngestInput(
            document_id="doc-prune",
            document_name="Prune Guide",
            file_type="md",
            markdown="# Title\nshort body only\n",
        )
    )

    after = await engine.search("word", rerank_threshold=0.0, top_k=10)
    after_count = len([r for r in after if r.document_id == "doc-prune"])

    assert before_count > after_count


@pytest.mark.asyncio
async def test_ingest_overwrites_before_pruning_stale_ids() -> None:
    vectors = RecordingVectors()
    engine = HaystackRagEngine(
        settings=HaystackSettings(
            embed_dimension=1,
            parent_max_words=100,
            child_max_words=100,
            child_overlap_words=0,
        ),
        embedder=StubEmbedder(),
        vectors=vectors,
        reranker=StubReranker(),
        captioner=None,
    )

    await engine.ingest(
        IngestInput(
            document_id="doc-order",
            document_name="Order Guide",
            file_type="md",
            markdown="# Title\nbody text\n",
        )
    )

    assert vectors.calls[0] == ("list_chunk_ids_by_document", "doc-order")
    assert vectors.calls[1][0] == "upsert_many"
    assert vectors.calls[2] == ("delete_many", ["doc-order::stale"])
    assert all(call[0] != "delete_by_document" for call in vectors.calls)
