from __future__ import annotations

from pathlib import Path

from app.core.config import load_settings

CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


def test_load_settings_offline_defaults(monkeypatch) -> None:
    monkeypatch.delenv("RAG_WORKER_URL", raising=False)
    monkeypatch.delenv("RAG_SEARCH_TIMEOUT_SECONDS", raising=False)
    settings = load_settings(CONFIG)
    assert settings.rag_worker_url == "http://rag-worker:8000"
    assert settings.search_timeout_seconds == 30.0
    assert settings.rerank_model == "gpt-4o-mini"
    assert settings.rerank_timeout_seconds == 30.0
    assert settings.rerank_batch_size == 8
    assert settings.rerank_passage_chars == 800
    assert settings.top_k_candidates == 20
    assert settings.tool_spec("rag_search").enabled is True
    assert settings.tool_spec("rag_search").params["search"]["rag_worker_url"] == "http://rag-worker:8000"
    assert settings.tool_spec("hr_query").enabled is False
    assert settings.tool_spec("hr_query").params["params"]["hr_service_url"] == "http://hr-service:8004"
    assert settings.tool_spec("hr_query").params["params"]["internal_token"] == ""


def test_load_settings_reads_rag_worker_url_from_env(monkeypatch) -> None:
    monkeypatch.setenv("RAG_WORKER_URL", "http://rag-worker.example:9000")
    monkeypatch.setenv("RAG_SEARCH_TIMEOUT_SECONDS", "12")
    settings = load_settings(CONFIG)
    assert settings.rag_worker_url == "http://rag-worker.example:9000"
    assert settings.search_timeout_seconds == 12.0
