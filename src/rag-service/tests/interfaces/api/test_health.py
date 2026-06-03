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
    assert body["reasons"]


def test_production_startup_fails_closed_when_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AI_PROVIDER", "offline")
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
