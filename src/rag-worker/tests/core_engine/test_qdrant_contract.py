from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from core_engine.contract import resolve_vectorstore_contract
from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.qdrant_contract import (
    VectorstoreContractError,
    check_stamp,
    verify_contract_or_raise,
    write_contract_stamp,
)

RAG_WORKER_ROOT = Path(__file__).resolve().parents[2]


def _contract(model: str, dim: int):
    return resolve_vectorstore_contract(
        provider="qdrant", collection="rag_chatbot", embed_model=model, dimension=dim
    )


# --- check_stamp: pure decision logic (không cần Qdrant) ---------------------


def test_check_stamp_passes_on_matching_fingerprint() -> None:
    contract = _contract("offline", 256)
    stamp = {"fingerprint": contract.fingerprint, "embed_model": "offline", "dimension": 256}
    check_stamp(stamp, contract)  # không raise


def test_check_stamp_raises_when_stamp_missing() -> None:
    with pytest.raises(VectorstoreContractError, match="Thiếu dấu niêm"):
        check_stamp(None, _contract("offline", 256))


def test_check_stamp_raises_on_fingerprint_mismatch() -> None:
    contract = _contract("offline", 256)
    stamp = {"fingerprint": "deadbeefdeadbeef", "embed_model": "bge-m3", "dimension": 1024}
    with pytest.raises(VectorstoreContractError, match="Fingerprint lệch"):
        check_stamp(stamp, contract)


# --- roundtrip với Qdrant in-process (path chung để write+verify share store) -


def _cfg(path: Path, model: str, dim: int) -> VectorStoreConfig:
    return VectorStoreConfig(
        provider="qdrant",
        collection="rag_chatbot",
        embed_model=model,
        dimension=dim,
        options={"path": str(path)},
    )


def test_verify_passes_after_producer_stamp(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "q", "offline", 256)
    asyncio.run(write_contract_stamp(cfg, written_by="rag-worker"))
    result = asyncio.run(verify_contract_or_raise(cfg, expect_data_collection=False))
    assert result.fingerprint == cfg.contract().fingerprint


def test_verify_raises_on_model_drift(tmp_path: Path) -> None:
    store = tmp_path / "q"
    producer = _cfg(store, "offline", 256)
    asyncio.run(write_contract_stamp(producer, written_by="rag-worker"))
    # Consumer dùng model khác -> index_id khác -> không thấy dấu niêm -> fail-closed.
    consumer = _cfg(store, "bge-m3", 1024)
    with pytest.raises(VectorstoreContractError):
        asyncio.run(verify_contract_or_raise(consumer, expect_data_collection=False))


# --- dependency hygiene: read-path KHÔNG được kéo ocr (dep ingest nặng) ------


def test_read_path_does_not_import_ocr() -> None:
    code = (
        "import sys; "
        "import core_engine.contract, core_engine.embedding.service, "
        "core_engine.vectorstore.config, core_engine.vectorstore.qdrant_contract, "
        "core_engine.rerank, core_engine.engine, core_engine.mapping; "
        "bad=[m for m in sys.modules if m.startswith('core_engine.ocr')]; "
        "assert not bad, 'read-path imports ingest-only ocr: %r' % bad"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(RAG_WORKER_ROOT),
        env={"PYTHONPATH": str(RAG_WORKER_ROOT), "PYTHONUTF8": "1", **_os_environ()},
    )
    assert result.returncode == 0, result.stderr


def _os_environ() -> dict[str, str]:
    import os

    return dict(os.environ)
