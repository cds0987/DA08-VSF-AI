from fastapi.testclient import TestClient
import pytest

from app.interfaces.api import main as main_module
from app.interfaces.api.main import create_app
from app.interfaces.api.runtime import HealthReport


def test_health_reports_unhealthy_when_running_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_production_startup_fails_closed_when_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///prod-metadata.db")
    monkeypatch.delenv("VECTOR_DB_URL", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)

    with pytest.raises(RuntimeError, match="Production fail-closed"):
        with TestClient(create_app()):
            pass


def test_invalid_runtime_settings_fail_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("SEARCH_TOP_K", "1")
    monkeypatch.setenv("RERANK_TOP_K", "3")

    with pytest.raises(ValueError, match="SEARCH_TOP_K must be >= RERANK_TOP_K"):
        with TestClient(create_app()):
            pass


def test_production_requires_durable_metadata_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_postgres_database_url_must_use_psycopg_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/rag")

    with pytest.raises(ValueError, match="postgresql\\+psycopg://"):
        with TestClient(create_app()):
            pass


def test_collection_name_must_not_preencode_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    with pytest.raises(ValueError, match="API key"):
        with TestClient(create_app()):
            pass


def test_remote_vector_backend_can_require_api_key_via_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("VECTOR_DB_PROVIDER", "qdrant")
    monkeypatch.setenv("VECTOR_DB_URL", "http://localhost:6333")
    monkeypatch.setenv("VECTOR_DB_REQUIRE_API_KEY", "1")
    monkeypatch.delenv("VECTOR_DB_API_KEY", raising=False)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)

    with pytest.raises(ValueError, match="VECTOR_DB_API_KEY is required"):
        with TestClient(create_app()):
            pass


def test_qdrant_cloud_requires_api_key_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("VECTOR_DB_PROVIDER", "qdrant")
    monkeypatch.setenv("VECTOR_DB_URL", "https://example.eu-central.aws.cloud.qdrant.io")
    monkeypatch.delenv("VECTOR_DB_REQUIRE_API_KEY", raising=False)
    monkeypatch.delenv("VECTOR_DB_API_KEY", raising=False)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)

    with pytest.raises(ValueError, match="VECTOR_DB_API_KEY is required"):
        with TestClient(create_app()):
            pass


def test_invalid_job_log_retention_days_fail_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("JOBLOG_RETENTION_DAYS", "0")

    with pytest.raises(ValueError, match="JOBLOG_RETENTION_DAYS must be > 0"):
        with TestClient(create_app()):
            pass


def test_readiness_recomputes_live_health_on_each_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    calls = {"count": 0}

    async def fake_compute_health(runtime) -> HealthReport:
        calls["count"] += 1
        return HealthReport(
            status="healthy" if calls["count"] == 1 else "unhealthy",
            app_env="development",
            ai_provider="offline",
            vector_provider="qdrant",
            vector_deployment="in_process",
            vector_index="rag_chatbot__d1024",
            metadata_backend="in_memory",
            reasons=[] if calls["count"] == 1 else ["vector down"],
        )

    monkeypatch.setattr(main_module, "compute_health", fake_compute_health)

    with TestClient(create_app()) as client:
        first = client.get("/readyz")
        second = client.get("/readyz")

    assert first.status_code == 200
    assert second.status_code == 503
    assert second.json()["reasons"] == ["vector down"]


def test_request_body_limit_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "8")

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/ingest",
            content=b"0123456789",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413


def test_rate_limit_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")

    with TestClient(create_app()) as client:
        first = client.get("/api/does-not-exist")
        second = client.get("/api/does-not-exist")

    assert first.status_code == 404
    assert second.status_code == 429


def test_health_routes_bypass_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")

    with TestClient(create_app()) as client:
        first = client.get("/livez")
        second = client.get("/livez")

    assert first.status_code == 200
    assert second.status_code == 200
