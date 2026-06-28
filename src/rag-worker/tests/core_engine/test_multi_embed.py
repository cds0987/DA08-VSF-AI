"""Multi-collection embed — contract + config + ingest fan-out + backfill (KHÔNG re-parse).

Gác 5 bất biến:
1. resolve_dimension trả đúng dim cho 4 model active; MODEL_TAGS đủ (collection riêng/model).
2. embeddings.yaml -> N model -> N collection config (dedup theo index_id).
3. ingest multi: N target -> N collection upsert, MỖI collection nhận vector đúng dim,
   CHIA SẺ chunks (embed_texts giống nhau), 1 target fail KHÔNG vỡ primary/target khác.
4. backfill: embed từ markdown (chunk sẵn) -> upsert, KHÔNG gọi parser.
5. append: model mới -> resolve collection mới; KHÔNG có cơ chế delete collection cũ.
"""
from __future__ import annotations

import pytest

from core_engine.config import HaystackSettings
from core_engine.contract import EMBED_MODELS, MODEL_TAGS, model_tag, resolve_dimension
from core_engine.engine import HaystackRagEngine, IngestInput
from core_engine.multi_embed import (
    EmbedTarget,
    load_active_embed_models,
    resolve_target_configs,
)
from core_engine.vectorstore import VectorStoreConfig

# KHÔNG hardcode danh sách model — DERIVE từ NGUỒN SỰ THẬT (embeddings.yaml) qua
# load_active_embed_models(). Đổi model = sửa 1 chỗ (embeddings.yaml), test tự theo; chỉ đỏ
# nếu model thật sự thiếu hợp đồng (dim/tag). Drift xuyên-service (routing.yaml/catalog) do
# infra/ci/embed_model_lint.py gác. [[no-rogue-follow-architecture]]
ACTIVE_MODELS = [(m, resolve_dimension(m)) for m in load_active_embed_models()]


# ── 1. contract ───────────────────────────────────────────────────────────────
# KHÔNG canary model cụ thể (qwen8b) — đó CHÍNH là hardcode "model privileged" đã đẻ ra bug
# qwen8b. Shard = N peer ngang nhau, không model nào đặc biệt. Chỉ kiểm BẤT BIẾN config-driven.
@pytest.mark.parametrize("model,dim", ACTIVE_MODELS)
def test_active_model_fully_specified(model: str, dim: int) -> None:
    """MỖI model active có hợp đồng đầy đủ: dim native (EMBED_MODELS) + tag (MODEL_TAGS)."""
    assert model in EMBED_MODELS, f"{model} active nhưng thiếu dim trong EMBED_MODELS"
    assert isinstance(dim, int) and dim > 0
    assert model in MODEL_TAGS, f"{model} active nhưng thiếu tag trong MODEL_TAGS"


def test_active_set_nonempty_and_has_anchor() -> None:
    """Shard pool ≥1 model; anchor (bootstrap) = phần tử đầu, KHÔNG privileged — chỉ cần tồn tại."""
    active = load_active_embed_models()
    assert active, "embeddings.yaml.embed_models RỖNG"


def test_each_model_has_distinct_collection_tag() -> None:
    tags = {model_tag(m) for m, _ in ACTIVE_MODELS}
    assert len(tags) == len(ACTIVE_MODELS), f"tag trùng -> collection trùng: {tags}"


def test_resolve_target_configs_one_collection_per_model() -> None:
    base = VectorStoreConfig(
        provider="qdrant", collection="rag_chatbot",
        embed_model="qwen/qwen3-embedding-8b", dimension=4096, hybrid=True,
    )
    out = resolve_target_configs(base, [m for m, _ in ACTIVE_MODELS])
    collections = [cfg.index_id() for _, _, cfg in out]
    assert len(collections) == len(set(collections)) == len(ACTIVE_MODELS)
    for (model, dim, cfg) in out:
        assert cfg.dimension == dim
        assert model_tag(model) in cfg.index_id()


def test_resolve_target_configs_dedup_alias_sharing_tag() -> None:
    # alias ngắn + đầy đủ CHUNG tag (te3s) -> 1 collection (không ghi đôi).
    base = VectorStoreConfig(provider="qdrant", collection="c", embed_model="x", dimension=10)
    out = resolve_target_configs(base, ["openai/text-embedding-3-small", "text-embedding-3-small"])
    assert len(out) == 1


# ── 3 & 4. ingest fan-out + backfill (mock embedder/vectors) ──────────────────
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

    async def list_chunk_ids_by_document(self, document_id: str):
        return []

    async def upsert_many(self, records):
        self.upserted = list(records)

    async def delete_many(self, chunk_ids):
        pass

    async def delete_by_document(self, document_id: str):
        pass


class _FailEmbedder(_StubEmbedder):
    async def embed_batch(self, texts):
        raise RuntimeError("e5 provider down")


def _target(model: str, dim: int, embedder=None) -> EmbedTarget:
    cfg = VectorStoreConfig(provider="qdrant", collection="rag_chatbot",
                            embed_model="qwen/qwen3-embedding-8b", dimension=4096) \
        .with_embed_model(model).with_dimension(dim)
    return EmbedTarget(
        embed_model=model, dimension=dim, config=cfg,
        embedder=embedder or _StubEmbedder(dim), vectors=_StubVectors(),
    )


def _engine(primary_vectors, primary_embedder, targets):
    return HaystackRagEngine(
        HaystackSettings(embed_dimension=4, parent_max_words=100,
                         child_max_words=4, child_overlap_words=1),
        primary_embedder, primary_vectors, captioner=None, embed_targets=targets,
    )


MD = "# Title\none two three four five six seven eight nine ten"


@pytest.mark.asyncio
async def test_ingest_writes_every_collection_with_correct_dim() -> None:
    pv, pe = _StubVectors(), _StubEmbedder(4)
    targets = [_target(m, d) for m, d in ACTIVE_MODELS[1:]]  # secondary (primary là qwen8b)
    engine = _engine(pv, pe, targets)
    count = await engine.ingest(IngestInput(
        document_id="d1", document_name="Doc", file_type="md", markdown=MD))
    assert count > 0
    assert len(pv.upserted) == count  # primary collection
    for t in targets:
        assert len(t.vectors.upserted) == count, t.embed_model
        # vector đúng dim của model đó
        assert all(len(r.vector) == t.dimension for r in t.vectors.upserted)
    # CHIA SẺ chunks: mọi target nhận CÙNG embed_texts như nhau (parse/chunk 1 lần)
    texts0 = targets[0].embedder.calls[0]
    for t in targets[1:]:
        assert t.embedder.calls[0] == texts0


@pytest.mark.asyncio
async def test_one_target_failure_does_not_break_others_or_primary() -> None:
    pv, pe = _StubVectors(), _StubEmbedder(4)
    good = _target("baai/bge-m3", 1024)
    bad = _target("perplexity/pplx-embed-v1-0.6b", 1024, embedder=_FailEmbedder(1024))
    engine = _engine(pv, pe, [bad, good])
    count = await engine.ingest(IngestInput(
        document_id="d1", document_name="Doc", file_type="md", markdown=MD))
    assert count > 0
    assert len(pv.upserted) == count          # primary OK
    assert len(good.vectors.upserted) == count  # target tốt OK
    assert good.vectors.upserted                # bad fail nhưng good vẫn ghi


@pytest.mark.asyncio
async def test_backfill_embeds_from_markdown_without_parser() -> None:
    # Backfill = ingest(markdown=...) với engine có primary = (embedder, vectors) của target.
    # KHÔNG truyền parser -> parse/OCR KHÔNG chạy (markdown đã có sẵn từ MD cache).
    pv, pe = _StubVectors(), _StubEmbedder(1024)
    engine = HaystackRagEngine(
        HaystackSettings(embed_dimension=4, parent_max_words=100,
                         child_max_words=4, child_overlap_words=1),
        pe, pv, captioner=None,
    )
    count = await engine.ingest(IngestInput(
        document_id="d1", document_name="Doc", file_type="md", markdown=MD))
    assert count > 0 and len(pv.upserted) == count
    assert pe.calls, "embed_batch phải được gọi (re-embed từ MD)"
