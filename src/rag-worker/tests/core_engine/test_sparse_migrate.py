"""Integration scroll-copy migrate sparse: dựng source hybrid (sparse cũ) trên Qdrant
on-disk, chạy migrate -> target __s2 phải: tồn tại, schema sparse modifier=IDF, count khớp,
sparse được TÍNH LẠI (BM25 document) còn dense GIỮ NGUYÊN, và hybrid query chạy được.
"""
from __future__ import annotations

import pytest

qmodels = pytest.importorskip("qdrant_client.models")
from qdrant_client import QdrantClient  # noqa: E402

from core_engine.contract import index_id as build_index_id  # noqa: E402
from core_engine.vectorstore.config import VectorStoreConfig  # noqa: E402
from scripts.migrate_sparse_version import run as migrate_run  # noqa: E402
from scripts.verify_bm25_collection import run as verify_run  # noqa: E402

_DIM = 256


def _make_config(path: str) -> VectorStoreConfig:
    return VectorStoreConfig(
        provider="qdrant", collection="rag_chatbot", embed_model="offline",
        dimension=_DIM, url="", hybrid=True, options={"path": path},
    )


def _seed_source(path: str, source: str, n: int) -> None:
    client = QdrantClient(path=path)
    try:
        client.create_collection(
            collection_name=source,
            vectors_config={"dense": qmodels.VectorParams(size=_DIM, distance=qmodels.Distance.COSINE)},
            sparse_vectors_config={"sparse": qmodels.SparseVectorParams()},  # CŨ: không IDF
        )
        client.create_payload_index(collection_name=source, field_name="document_id", field_schema="keyword")
        pts = []
        for i in range(n):
            dense = [float((i + 1) % 7) / 7.0] * _DIM
            pts.append(qmodels.PointStruct(
                id=i + 1,
                vector={"dense": dense, "sparse": qmodels.SparseVector(indices=[i + 1], values=[1.0])},
                payload={"document_id": f"d{i}", "bm25_text": f"nghi phep nam thu {i}", "chunk_id": f"c{i}"},
            ))
        client.upsert(collection_name=source, points=pts, wait=True)
    finally:
        client.close()


def test_scroll_copy_migrate(tmp_path):
    path = str(tmp_path / "qdrant")
    cfg = _make_config(path)
    source = build_index_id(cfg.collection, cfg.embed_model, cfg.dimension, sparse_version=0)
    target = cfg.index_id()
    assert target.endswith("__s2") and source != target

    _seed_source(path, source, n=5)

    rc = migrate_run(dry_run=False, batch=2, limit=None, config=cfg)
    assert rc == 0

    client = QdrantClient(path=path)
    try:
        assert client.collection_exists(target)
        # count khớp
        assert client.count(collection_name=target, exact=True).count == 5
        # schema sparse có modifier IDF
        info = client.get_collection(target)
        sparse_cfg = info.config.params.sparse_vectors["sparse"]
        assert getattr(sparse_cfg, "modifier", None) == qmodels.Modifier.IDF
        # dense GIỮ NGUYÊN; sparse được tính lại (BM25 doc -> value != 1.0 raw cũ)
        recs = client.retrieve(collection_name=target, ids=[1], with_vectors=True, with_payload=True)
        vec = recs[0].vector
        assert "dense" in vec and "sparse" in vec
        sp = vec["sparse"]
        assert len(sp.indices) >= 1
        # stamp ghi được
        meta = "rag_chatbot__meta"
        assert client.collection_exists(meta)
    finally:
        client.close()


def test_verify_passes_after_migrate(tmp_path):
    path = str(tmp_path / "qdrant")
    cfg = _make_config(path)
    source = build_index_id(cfg.collection, cfg.embed_model, cfg.dimension, sparse_version=0)
    _seed_source(path, source, n=4)
    assert migrate_run(dry_run=False, batch=2, limit=None, config=cfg) == 0
    # verify mở client riêng cùng path -> phải PASS (schema IDF + count + sparse query).
    assert verify_run(config=cfg) == 0


def test_migrate_noop_when_no_source(tmp_path):
    """Không có source -> migrate trả 1 (caller fallback reingest GCS)."""
    cfg = _make_config(str(tmp_path / "qdrant"))
    assert migrate_run(dry_run=False, batch=2, limit=None, config=cfg) == 1
