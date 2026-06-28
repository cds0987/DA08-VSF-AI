"""Shard N/5 — mỗi doc embed vào CHỈ 1 collection (round-robin hash theo doc-id).

Gác bất biến:
1. select_shard_index: deterministic (cùng doc -> cùng slot), phủ đều, fallback an toàn.
2. load_embed_mode: yaml/env -> replicate|shard, default replicate.
3. WRITE shard: 5 doc-id khác -> phân bố ~đều pool; cùng doc-id -> cùng collection;
   slot!=primary -> primary KHÔNG ghi, chỉ 1 secondary ghi.
4. WRITE replicate (mode off): primary + MỌI secondary ghi (backward compat).
5. READ merge: query mỗi collection bằng model riêng -> gộp + dedup theo chunk_id +
   ACL filter giữ; 1 collection lỗi không vỡ.
"""
from __future__ import annotations

from collections import Counter

import pytest

from app.application.use_cases.search.search_use_case import SearchUseCase
from core_engine.config import HaystackSettings
from core_engine.engine import HaystackRagEngine, IngestInput
from core_engine.multi_embed import (
    EMBED_MODE_REPLICATE,
    EMBED_MODE_SHARD,
    EmbedTarget,
    load_embed_mode,
    select_shard_index,
)
from core_engine.vectorstore import VectorStoreConfig
from core_engine.vectorstore.types import SearchHit

ACTIVE_5 = [
    ("qwen/qwen3-embedding-8b", 4096),
    ("intfloat/multilingual-e5-large", 1024),
    ("baai/bge-m3", 1024),
    ("openai/text-embedding-3-small", 1536),
    ("perplexity/pplx-embed-v1-0.6b", 1024),
]

MD = "# Title\none two three four five six seven eight nine ten"


# ── 1. select_shard_index ─────────────────────────────────────────────────────
def test_select_shard_index_deterministic() -> None:
    assert select_shard_index("doc-abc", 5) == select_shard_index("doc-abc", 5)


def test_select_shard_index_in_range_and_spreads() -> None:
    counts = Counter(select_shard_index(f"doc-{i}", 5) for i in range(500))
    assert set(counts) <= set(range(5))
    # phủ đều: mỗi slot có mặt, không slot nào ôm >40% (random ~20%/slot)
    assert len(counts) == 5
    assert max(counts.values()) < 0.4 * 500


def test_select_shard_index_empty_docid_fallback_slot0() -> None:
    assert select_shard_index("", 5) == 0
    assert select_shard_index(None, 5) == 0
    assert select_shard_index("doc", 0) == 0


# ── 2. load_embed_mode ────────────────────────────────────────────────────────
def test_load_embed_mode_default_replicate(tmp_path) -> None:
    assert load_embed_mode(tmp_path / "nope.yaml") == EMBED_MODE_REPLICATE


def test_load_embed_mode_reads_shard(tmp_path) -> None:
    p = tmp_path / "embeddings.yaml"
    p.write_text("mode: shard\nembed_models: [a]\n", encoding="utf-8")
    assert load_embed_mode(p) == EMBED_MODE_SHARD


def test_load_embed_mode_invalid_falls_back(tmp_path) -> None:
    p = tmp_path / "embeddings.yaml"
    p.write_text("mode: bogus\n", encoding="utf-8")
    assert load_embed_mode(p) == EMBED_MODE_REPLICATE


def test_load_embed_mode_env_override(tmp_path, monkeypatch) -> None:
    p = tmp_path / "embeddings.yaml"
    p.write_text("mode: replicate\n", encoding="utf-8")
    monkeypatch.setenv("MULTI_EMBED_MODE", "shard")
    assert load_embed_mode(p) == EMBED_MODE_SHARD


# ── stubs ─────────────────────────────────────────────────────────────────────
class _StubEmbedder:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    async def embed(self, text: str):
        return [0.0] * self.dim

    async def embed_batch(self, texts):
        self.calls.append(list(texts))
        return [[float(i)] * self.dim for i in range(len(texts))]


class _StubVectors:
    def __init__(self) -> None:
        self.upserted: list = []
        self.deleted: list = []

    async def list_chunk_ids_by_document(self, document_id: str):
        return []

    async def upsert_many(self, records):
        self.upserted = list(records)

    async def delete_many(self, chunk_ids):
        self.deleted = list(chunk_ids)

    async def delete_by_document(self, document_id: str):
        pass


def _target(model: str, dim: int, embedder=None) -> EmbedTarget:
    cfg = VectorStoreConfig(provider="qdrant", collection="rag_chatbot",
                            embed_model="qwen/qwen3-embedding-8b", dimension=4096) \
        .with_embed_model(model).with_dimension(dim)
    return EmbedTarget(
        embed_model=model, dimension=dim, config=cfg,
        embedder=embedder or _StubEmbedder(dim), vectors=_StubVectors(),
    )


def _engine(primary_vectors, primary_embedder, targets, shard_mode):
    return HaystackRagEngine(
        HaystackSettings(embed_dimension=4, parent_max_words=100,
                         child_max_words=4, child_overlap_words=1),
        primary_embedder, primary_vectors, captioner=None,
        embed_targets=targets, shard_mode=shard_mode,
    )


def _fresh_targets():
    return [_target(m, d) for m, d in ACTIVE_5[1:]]  # 4 secondary (primary = qwen8b)


# ── 3. WRITE shard ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_shard_writes_exactly_one_collection_per_doc() -> None:
    # Tìm 1 doc-id mà slot != 0 (rơi vào secondary) để kiểm primary KHÔNG ghi.
    pool = 5
    doc_secondary = next(f"d{i}" for i in range(1000) if select_shard_index(f"d{i}", pool) != 0)
    slot = select_shard_index(doc_secondary, pool)

    pv, pe = _StubVectors(), _StubEmbedder(4)
    targets = _fresh_targets()
    engine = _engine(pv, pe, targets, shard_mode=True)
    count = await engine.ingest(IngestInput(
        document_id=doc_secondary, document_name="Doc", file_type="md", markdown=MD))
    assert count > 0
    # primary KHÔNG nhận doc này
    assert pv.upserted == []
    # đúng 1 secondary (slot-1) ghi; các secondary khác trống
    written = [i for i, t in enumerate(targets) if t.vectors.upserted]
    assert written == [slot - 1]
    assert len(targets[slot - 1].vectors.upserted) == count


@pytest.mark.asyncio
async def test_shard_primary_slot_writes_only_primary() -> None:
    pool = 5
    doc_primary = next(f"p{i}" for i in range(1000) if select_shard_index(f"p{i}", pool) == 0)
    pv, pe = _StubVectors(), _StubEmbedder(4)
    targets = _fresh_targets()
    engine = _engine(pv, pe, targets, shard_mode=True)
    count = await engine.ingest(IngestInput(
        document_id=doc_primary, document_name="Doc", file_type="md", markdown=MD))
    assert count > 0
    assert len(pv.upserted) == count
    assert all(not t.vectors.upserted for t in targets)  # không secondary nào ghi


@pytest.mark.asyncio
async def test_shard_same_docid_same_collection_deterministic() -> None:
    async def _where(doc_id: str) -> str:
        pv, pe = _StubVectors(), _StubEmbedder(4)
        targets = _fresh_targets()
        engine = _engine(pv, pe, targets, shard_mode=True)
        await engine.ingest(IngestInput(
            document_id=doc_id, document_name="Doc", file_type="md", markdown=MD))
        if pv.upserted:
            return "primary"
        return next(t.embed_model for t in targets if t.vectors.upserted)

    assert await _where("stable-doc") == await _where("stable-doc")


@pytest.mark.asyncio
async def test_shard_distributes_5_docs_across_pool() -> None:
    where = []
    for i in range(5):
        pv, pe = _StubVectors(), _StubEmbedder(4)
        targets = _fresh_targets()
        engine = _engine(pv, pe, targets, shard_mode=True)
        await engine.ingest(IngestInput(
            document_id=f"doc-{i}", document_name="D", file_type="md", markdown=MD))
        slot = 0 if pv.upserted else 1 + next(
            i for i, t in enumerate(targets) if t.vectors.upserted)
        where.append(slot)
    # mỗi doc đi vào đúng slot theo hash (không replicate)
    assert where == [select_shard_index(f"doc-{i}", 5) for i in range(5)]


# ── 4. WRITE replicate (backward compat) ──────────────────────────────────────
@pytest.mark.asyncio
async def test_replicate_mode_writes_all_collections() -> None:
    pv, pe = _StubVectors(), _StubEmbedder(4)
    targets = _fresh_targets()
    engine = _engine(pv, pe, targets, shard_mode=False)
    count = await engine.ingest(IngestInput(
        document_id="doc-x", document_name="Doc", file_type="md", markdown=MD))
    assert count > 0
    assert len(pv.upserted) == count
    for t in targets:
        assert len(t.vectors.upserted) == count, t.embed_model


# ── 5. READ merge ─────────────────────────────────────────────────────────────
class _ReadStubEmbedder:
    def __init__(self, dim: int) -> None:
        self.dim = dim

    async def embed(self, text: str):
        return [0.1] * self.dim


class _ReadStubVectors:
    def __init__(self, hits, fail=False) -> None:
        self._hits = hits
        self._fail = fail
        self.seen_document_ids = "UNSET"

    async def search(self, *, query_vector, query_text, top_k, document_ids):
        if self._fail:
            raise RuntimeError("collection down")
        self.seen_document_ids = document_ids
        return list(self._hits)


def _read_target(model, dim, hits, fail=False) -> EmbedTarget:
    cfg = VectorStoreConfig(provider="qdrant", collection="c",
                            embed_model="qwen/qwen3-embedding-8b", dimension=4096) \
        .with_embed_model(model).with_dimension(dim)
    t = EmbedTarget(model, dim, cfg, _ReadStubEmbedder(dim), _ReadStubVectors(hits, fail))
    return t


def _hit(chunk_id, score, doc="d1"):
    return SearchHit(chunk_id=chunk_id, document_id=doc, score=score, child_text=chunk_id)


@pytest.mark.asyncio
async def test_read_merge_dedups_and_keeps_highest_score() -> None:
    t1 = _read_target("qwen/qwen3-embedding-8b", 4096, [_hit("c1", 0.9), _hit("c2", 0.5)])
    t2 = _read_target("baai/bge-m3", 1024, [_hit("c1", 0.3), _hit("c3", 0.7)])
    uc = SearchUseCase(t1.embedder, t1.vectors, read_targets=[t1, t2])
    out = await uc.search(query="q", document_ids=["d1"], top_k=10)
    ids = [c.chunk_id for c in out]
    # dedup c1 (giữ 0.9), gộp c2/c3 -> 3 ứng viên, sort theo score desc
    assert ids == ["c1", "c3", "c2"]
    assert out[0].score == 0.9


@pytest.mark.asyncio
async def test_read_merge_passes_acl_to_every_collection() -> None:
    t1 = _read_target("qwen/qwen3-embedding-8b", 4096, [_hit("c1", 0.9)])
    t2 = _read_target("baai/bge-m3", 1024, [_hit("c2", 0.8)])
    uc = SearchUseCase(t1.embedder, t1.vectors, read_targets=[t1, t2])
    await uc.search(query="q", document_ids=["docA", "docB"], top_k=5)
    assert t1.vectors.seen_document_ids == ["docA", "docB"]
    assert t2.vectors.seen_document_ids == ["docA", "docB"]


@pytest.mark.asyncio
async def test_read_merge_one_collection_failure_does_not_break() -> None:
    good = _read_target("qwen/qwen3-embedding-8b", 4096, [_hit("c1", 0.9)])
    bad = _read_target("baai/bge-m3", 1024, [], fail=True)
    uc = SearchUseCase(good.embedder, good.vectors, read_targets=[good, bad])
    out = await uc.search(query="q", document_ids=["d1"], top_k=5)
    assert [c.chunk_id for c in out] == ["c1"]


@pytest.mark.asyncio
async def test_no_read_targets_uses_single_collection_path() -> None:
    single = _ReadStubVectors([_hit("c1", 0.5)])
    uc = SearchUseCase(_ReadStubEmbedder(4), single)  # read_targets=None
    out = await uc.search(query="q", document_ids=["d1"], top_k=5)
    assert [c.chunk_id for c in out] == ["c1"]
    assert single.seen_document_ids == ["d1"]
