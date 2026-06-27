"""Regression cho 2 bug auto-migrate (2026-06-27) — gây collection lạc + reingest fail.

Bug 1: VectorStoreConfig.from_env() KHÔNG đọc EMBED_DIMENSION -> resolve native (8b=4096)
       thay vì override (2560) -> index_id lệch bootstrap_runtime -> auto_migrate tính target
       SAI -> tạo collection lạc d4096 + reingest nhầm chỗ.
Bug 2: is_qdrant_collection_missing_error đòi đúng chữ "doesn't exist"; Qdrant trả "Not Found"
       -> không nhận missing -> _retry_on_missing_collection không recreate -> 404 permanent-fail.
"""
from __future__ import annotations

import pytest

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.providers.qdrant.base import is_qdrant_collection_missing_error


def test_from_env_reads_embed_dimension_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("EMBED_BASE_URL", "http://ai-router:8010/v1")  # -> has_real_provider
    monkeypatch.setenv("EMBED_MODEL", "qwen/qwen3-embedding-8b")
    monkeypatch.setenv("EMBED_DIMENSION", "2560")  # MRL override (native=4096)
    monkeypatch.setenv("VECTOR_COLLECTION", "rag_chatbot")
    monkeypatch.setenv("VECTOR_HYBRID", "true")
    cfg = VectorStoreConfig.from_env()
    assert cfg.dimension == 2560, f"phải đọc EMBED_DIMENSION=2560 (không native 4096), got {cfg.dimension}"
    assert "qwen3emb8b__d2560__s2" in cfg.index_id(), cfg.index_id()


def test_missing_collection_detects_404_regardless_of_phrasing() -> None:
    from qdrant_client.http.exceptions import UnexpectedResponse

    def _resp(status: int, content: bytes) -> UnexpectedResponse:
        return UnexpectedResponse(
            status_code=status, reason_phrase="x", content=content, headers={}
        )

    # MỌI phrasing Qdrant cho collection thiếu (đổi giữa version) -> đều nhận missing.
    for content in (
        b'{"status":{"error":"Not found: Collection `c` not found"}}',     # phrasing MỚI (miss ở code cũ)
        b'{"status":{"error":"Collection `c` doesn\'t exist!"}}',          # phrasing CŨ
        b"",                                                               # content rỗng
    ):
        assert is_qdrant_collection_missing_error(_resp(404, content)) is True

    # Không phải 404 -> KHÔNG coi là missing (đừng recreate oan).
    assert is_qdrant_collection_missing_error(_resp(400, b"bad request")) is False
    assert is_qdrant_collection_missing_error(ValueError("x")) is False
