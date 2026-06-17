"""Test BM25 hybrid: _point + _collection_create_kwargs sinh named dense + sparse khi
config.hybrid=True; giữ vector trần khi False (KHÔNG đụng collection prod cũ).

Gọi method với probe (chỉ cần .config) -> không cần Qdrant thật / instantiate provider đầy đủ.
"""
from __future__ import annotations

import types

from qdrant_client import models

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.providers.qdrant.base import QdrantBase
from core_engine.vectorstore.sparse import sparse_encode
from core_engine.vectorstore.types import VectorRecord

_REC = VectorRecord(chunk_id="c1", vector=[0.1, 0.2, 0.3, 0.4],
                    payload={"bm25_text": "nghi phep nam", "document_id": "d1"})


def _probe(hybrid: bool):
    return types.SimpleNamespace(config=VectorStoreConfig(dimension=4, hybrid=hybrid))


def test_dense_mode_unchanged():
    p = _probe(hybrid=False)
    kwargs = QdrantBase._collection_create_kwargs(p)
    assert isinstance(kwargs["vectors_config"], models.VectorParams)   # vector trần
    assert "sparse_vectors_config" not in kwargs
    point = QdrantBase._point(p, _REC)
    assert isinstance(point.vector, list)                              # unnamed


def test_hybrid_mode_named_dense_and_sparse():
    p = _probe(hybrid=True)
    kwargs = QdrantBase._collection_create_kwargs(p)
    assert set(kwargs["vectors_config"].keys()) == {"dense"}           # named dense
    assert "sparse" in kwargs["sparse_vectors_config"]                 # sparse schema

    point = QdrantBase._point(p, _REC)
    assert set(point.vector.keys()) == {"dense", "sparse"}
    assert point.vector["dense"] == [0.1, 0.2, 0.3, 0.4]
    sparse = point.vector["sparse"]
    # sparse PHẢI khớp encode bm25_text bằng cùng hàm với mcp search
    exp_idx, exp_val = sparse_encode("nghi phep nam")
    assert list(sparse.indices) == exp_idx
    assert list(sparse.values) == exp_val


def test_hybrid_dimension_guard():
    p = _probe(hybrid=True)
    bad = VectorRecord(chunk_id="c2", vector=[0.1, 0.2], payload={})   # dim 2 != 4
    try:
        QdrantBase._point(p, bad)
        assert False, "phải raise khi sai dimension"
    except ValueError:
        pass
