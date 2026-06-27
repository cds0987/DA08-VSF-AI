"""Regression (2026-06-27): refactor mcp-thin xoá embed_api_key/embed_base_url khỏi McpSettings
NHƯNG rerank.build_reranker('llm') còn fallback settings.embed_api_key/embed_base_url -> khi
rerank_api_key RỖNG (e2e: RERANK_PROVIDER=llm không set RERANK_API_KEY) -> AttributeError ->
RagSearchTool.__init__ crash -> mcp KHÔNG đăng ký tool -> query-service mcp_pool_open_failed ->
worker CancelledError -> retrieved=0 (e2e đỏ, prod ổn vì rerank_api_key có giá trị).

Fix: config.load_settings fallback rerank_base_url/api_key sang env gateway (EMBED_*/OPENAI);
build_reranker chỉ dùng settings.rerank_* (KHÔNG còn embed_*).
"""
from __future__ import annotations

import dataclasses

from app.core.config import McpSettings, load_settings
from app.core.rerank import build_reranker


def test_mcp_settings_has_no_embed_fields() -> None:
    names = {f.name for f in dataclasses.fields(McpSettings)}
    assert "embed_api_key" not in names
    assert "embed_base_url" not in names


def test_rerank_api_key_falls_back_to_embed_api_key_env(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_API_KEY", "gateway-tok")
    monkeypatch.setenv("EMBED_BASE_URL", "http://ai-router:8010/v1")
    monkeypatch.delenv("RERANK_API_KEY", raising=False)
    monkeypatch.delenv("RERANK_BASE_URL", raising=False)
    s = load_settings()
    assert s.rerank_api_key == "gateway-tok"
    assert s.rerank_base_url == "http://ai-router:8010/v1"


def test_build_llm_reranker_with_empty_rerank_key_does_not_crash(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_API_KEY", "gateway-tok")
    monkeypatch.setenv("EMBED_BASE_URL", "http://ai-router:8010/v1")
    base = load_settings()
    s = dataclasses.replace(
        base, rerank_impl="llm", rerank_model="gpt-4o-mini",
        rerank_api_key="", rerank_base_url="",  # cấu hình KHÔNG khai key -> KHÔNG được AttributeError
    )
    reranker = build_reranker(s)  # trước fix: AttributeError 'embed_api_key'
    assert reranker.__class__.__name__ == "LlmReranker"
