from fastapi.testclient import TestClient
import pytest

from app.interfaces.api.main import create_app


def test_health_reports_unhealthy_when_running_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.delenv("VECTOR_DB_URL", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["ai_provider"] == "offline"
    assert body["vector_deployment"] == "in_process"
    assert body["metadata_backend"] == "in_memory"
    assert body["reasons"]


def test_production_startup_fails_closed_when_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///prod-metadata.db")
    monkeypatch.delenv("VECTOR_DB_URL", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)

    with pytest.raises(RuntimeError, match="Production fail-closed"):
        with TestClient(create_app()):
            pass


def test_invalid_runtime_settings_fail_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("SEARCH_TOP_K", "1")
    monkeypatch.setenv("RERANK_TOP_K", "3")

    with pytest.raises(ValueError, match="SEARCH_TOP_K must be >= RERANK_TOP_K"):
        with TestClient(create_app()):
            pass


def test_production_requires_durable_metadata_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("VECTOR_DB_URL", "http://localhost:6333")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(
        ValueError,
        match="DATABASE_URL must be configured in production",
    ):
        with TestClient(create_app()):
            pass


def test_collection_name_must_not_preencode_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("VECTOR_COLLECTION", "rag_chatbot__d1024")

    with pytest.raises(ValueError, match="VECTOR_COLLECTION must not encode dimension"):
        with TestClient(create_app()):
            pass


def test_openai_provider_requires_api_key_without_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    monkeypatch.delenv("CAPTION_API_KEY", raising=False)
    monkeypatch.delenv("RERANK_API_KEY", raising=False)
    monkeypatch.delenv("EMBED_BASE_URL", raising=False)
    monkeypatch.delenv("CAPTION_BASE_URL", raising=False)
    monkeypatch.delenv("RERANK_BASE_URL", raising=False)

    with pytest.raises(ValueError, match="thiếu API key"):
        with TestClient(create_app()):
            pass
