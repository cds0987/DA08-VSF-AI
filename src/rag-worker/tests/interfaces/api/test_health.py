from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.interfaces.api import main as main_module
from app.interfaces.api.main import create_app
from app.interfaces.api.runtime import HealthReport
from app.infrastructure.external.local_parser import LocalFileParser
from app.infrastructure.external.s3_parser import S3SourceParser


RAG_WORKER_CONFIG = Path(__file__).resolve().parents[2] / "config.yaml"


class _FakeVectorConfig:
    provider = "qdrant"
    deployment = "remote"

    def index_id(self) -> str:
        return "rag_chatbot__test__d256"

    def contract(self):
        class _Contract:
            fingerprint = "test-fingerprint"

        return _Contract()


class _FakeVectors:
    def __init__(self) -> None:
        self.config = _FakeVectorConfig()

    async def list_chunk_ids_by_document(self, document_id: str) -> list[str]:
        return []


class _FakeEngine:
    def __init__(self) -> None:
        self.vectors = _FakeVectors()


def _configure_s3_pipeline_test(
    monkeypatch: pytest.MonkeyPatch,
    runtime_module,
    *,
    startup_reasons: list[str] | None = None,
    startup_warnings: list[str] | None = None,
) -> None:
    class _TestS3SourceParser(S3SourceParser):
        def startup_diagnostics(
            self,
            *,
            source_bucket: str | None = None,
        ) -> tuple[list[str], list[str]]:
            return list(startup_reasons or []), list(startup_warnings or [])

    monkeypatch.setenv("PIPELINE_CONFIG", str(RAG_WORKER_CONFIG))
    monkeypatch.setenv("PARSER_IMPL", "s3")
    monkeypatch.setenv("VECTOR_DB_URL", "http://vector.test:6333")
    monkeypatch.setattr(
        runtime_module,
        "resolve_parser",
        lambda name, **kwargs: _TestS3SourceParser(LocalFileParser(max_workers=1)),
    )
    monkeypatch.setattr(
        runtime_module,
        "build_engine_from_config",
        lambda *args, **kwargs: _FakeEngine(),
    )
    # write_contract_stamp ĐÃ GỠ khỏi startup (mcp-thin không verify) -> không cần patch.


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


def test_health_reports_storage_preflight_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.interfaces.api import runtime as runtime_module

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("S3_SOURCE_BUCKET", "docs-bucket")
    _configure_s3_pipeline_test(
        monkeypatch,
        runtime_module,
        startup_reasons=["Object storage preflight failed for bucket docs-bucket: 403"],
    )

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert "Object storage preflight failed for bucket docs-bucket: 403" in response.json()["reasons"]


def test_production_startup_fails_closed_on_storage_preflight_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.interfaces.api import runtime as runtime_module

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/rag")
    monkeypatch.setenv("S3_SOURCE_BUCKET", "docs-bucket")
    _configure_s3_pipeline_test(
        monkeypatch,
        runtime_module,
        startup_reasons=["Object storage preflight failed for bucket docs-bucket: 403"],
    )

    with pytest.raises(RuntimeError, match="Object storage preflight failed"):
        with TestClient(create_app()):
            pass


def test_invalid_runtime_settings_fail_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # rag-worker = INGEST-ONLY: không còn validate SEARCH_TOP_K/RERANK_TOP_K (search,
    # thuộc mcp-service). Kiểm setting INGEST sai (chunker) -> startup phải fail.
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("CHILD_MAX_WORDS", "10")
    monkeypatch.setenv("CHILD_OVERLAP_WORDS", "20")

    with pytest.raises(ValueError, match="CHILD_OVERLAP_WORDS must be < CHILD_MAX_WORDS"):
        with TestClient(create_app()):
            pass


def test_invalid_caption_enabled_value_fails_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("CAPTION_ENABLED", "maybe")

    with pytest.raises(ValueError, match="CAPTION_ENABLED must be one of"):
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
    monkeypatch.setenv("VECTOR_COLLECTION", "rag_chatbot__te3s__d1536")

    with pytest.raises(ValueError, match="VECTOR_COLLECTION must not encode model/dimension"):
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


def test_invalid_ingest_timeout_fails_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("INGEST_JOB_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValueError, match="INGEST_JOB_TIMEOUT_SECONDS must be > 0"):
        with TestClient(create_app()):
            pass


def test_invalid_embed_batch_size_fails_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("EMBED_BATCH_SIZE", "0")

    with pytest.raises(ValueError, match="EMBED_BATCH_SIZE must be > 0"):
        with TestClient(create_app()):
            pass


def test_invalid_ingest_timeout_fails_startup_with_pipeline_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("PIPELINE_CONFIG", str(RAG_WORKER_CONFIG))
    monkeypatch.setenv("VECTOR_DB_URL", "http://localhost:6333")
    monkeypatch.setenv("INGEST_JOB_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValueError, match="INGEST_JOB_TIMEOUT_SECONDS must be > 0"):
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
            vector_index="rag_chatbot__offline__d256",
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


def test_search_http_route_is_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Query-side retrieval ĐÃ chuyển từ mcp về rag-worker: POST /api/search tồn tại.
    # Body sai schema (thiếu "query") -> 422 (route có thật), KHÔNG còn 404 như trước.
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")

    with TestClient(create_app()) as client:
        bad_body = client.post("/api/search", json={"query_text": "reset password"})
        served = client.post("/api/search", json={"query": "reset password"})

    assert bad_body.status_code == 422
    # offline provider + Qdrant in-memory rỗng -> 200 với candidates rỗng (ACL None
    # -> __no_access__ cũng rỗng). Điểm chốt: route được phục vụ, không 404.
    assert served.status_code == 200
    assert served.json() == {"candidates": []}


def test_internal_rpc_search_bypasses_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: /api/search là RPC NỘI BỘ (mcp -> rag-worker, mọi call từ 1 IP mcp).
    # Trước fix: rate-limit per-IP (default 60/60s) bóp search còn ~1/giây -> 429 dưới tải
    # chat -> retrieval fail -> chat trả rỗng. Sau fix: search MIỄN rate-limit per-IP.
    # RATE_LIMIT_REQUESTS=1 nhưng nhiều search liên tiếp PHẢI vẫn 200 (không 429).
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")

    with TestClient(create_app()) as client:
        responses = [client.post("/api/search", json={"query": "x"}) for _ in range(5)]

    codes = [r.status_code for r in responses]
    assert codes == [200] * 5, codes  # KHÔNG có 429


def test_external_path_still_rate_limited_after_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fix CHỈ miễn path internal RPC; path khác (vd /api/does-not-exist) VẪN bị rate-limit.
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_PROVIDER", "offline")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")

    with TestClient(create_app()) as client:
        first = client.get("/api/other")
        second = client.get("/api/other")

    assert first.status_code in (404, 405)
    assert second.status_code == 429
