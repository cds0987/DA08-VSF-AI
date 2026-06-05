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
    assert settings.contract().index_id == "rag_chatbot__offline__d256"
    assert settings.contract().fingerprint == "88048119fce054e3"
