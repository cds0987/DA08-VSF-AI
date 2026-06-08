from __future__ import annotations

from pathlib import Path

from app.core.config import load_settings

CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


def test_load_settings_offline_defaults(monkeypatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    monkeypatch.delenv("EMBED_DIMENSION", raising=False)
    settings = load_settings(CONFIG)
    assert settings.provider == "qdrant"
    assert settings.collection == "rag_chatbot"
    assert settings.embed_model == "offline"
    assert settings.dimension == 256
    assert settings.rerank_model == "gpt-4o-mini"
    assert settings.rerank_timeout_seconds == 30.0
    assert settings.rerank_batch_size == 8
    assert settings.rerank_passage_chars == 800
    assert settings.contract().index_id == "rag_chatbot__offline__d256"
    assert settings.contract().fingerprint == "88048119fce054e3"
    assert settings.tool_spec("rag_search").enabled is True
    assert settings.tool_spec("hr_query").enabled is False
