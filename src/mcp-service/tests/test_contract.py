from __future__ import annotations

import pytest

from app.core.contract import (
    VectorstoreContractError,
    check_stamp,
    index_id,
    model_tag,
    resolve_dimension,
    resolve_vectorstore_contract,
)


def test_offline_fingerprint_matches_rag_worker_constant() -> None:
    # Lock CROSS-IMPL parity: giá trị này PHẢI khớp rag-worker (CLI checker in ra
    # rag_chatbot__offline__d256 fp=88048119fce054e3). Lệch = mcp drift khỏi producer.
    contract = resolve_vectorstore_contract(
        provider="qdrant", collection="rag_chatbot", embed_model="offline", dimension=None
    )
    assert contract.index_id == "rag_chatbot__offline__d256"
    assert contract.fingerprint == "88048119fce054e3"


def test_model_tag_and_derive_dim() -> None:
    assert model_tag("text-embedding-3-small") == "te3s"
    assert resolve_dimension("text-embedding-3-small") == 1536
    assert resolve_dimension("bge-m3") == 1024
    assert index_id("rag_chatbot", "text-embedding-3-small", 1536) == "rag_chatbot__te3s__d1536"


def test_resolve_dimension_rejects_bad_override() -> None:
    with pytest.raises(ValueError):
        resolve_dimension("bge-m3", 999)


def test_check_stamp_pass_and_fail() -> None:
    contract = resolve_vectorstore_contract(
        provider="qdrant", collection="rag_chatbot", embed_model="offline", dimension=None
    )
    check_stamp({"fingerprint": contract.fingerprint}, contract)  # ok
    with pytest.raises(VectorstoreContractError, match="Thiếu dấu niêm"):
        check_stamp(None, contract)
    with pytest.raises(VectorstoreContractError, match="Fingerprint lệch"):
        check_stamp({"fingerprint": "deadbeefdeadbeef"}, contract)
