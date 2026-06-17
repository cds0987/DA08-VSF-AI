from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "query-service"
    app_env: str = "development"
    database_url: str | None = None

    @property
    def asyncpg_dsn(self) -> str | None:
        """DSN đã sạch cho asyncpg (xoá dialect SQLAlchemy). Repo dùng property này,
        KHÔNG tự cắt chuỗi -> đóng class lỗi DSN +psycopg (sự cố 2026-06-16)."""
        from app.infrastructure.db.dsn import to_asyncpg_dsn

        return to_asyncpg_dsn(self.database_url) if self.database_url else None

    auth_mode: str = "mock"
    jwt_secret_key: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    user_service_url: str = "http://localhost:8000"
    auth_http_timeout_seconds: float = 5.0

    redis_url: str = "redis://localhost:6379/0"

    llm_mode: str = "openai"
    openai_api_key: str | None = None
    openai_llm_model: str = "gpt-5.4-nano"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: int = 30

    # ── AI gateway (ai-router) ────────────────────────────────────────────────
    # openai_base_url RỖNG -> gọi THẲNG OpenAI (hành vi cũ, kill-switch tức thì). Set
    # http://ai-router:8010/v1 -> mọi LLM/embedding đi qua router (cân bằng key + cost-per-key).
    # ACTIVE prod từ 2026-06-17 (LLM_MODEL_ADAPTER=chat). Bài học: router chat_stream từng
    # trùng keyword 'stream' -> SSE vỡ; đã fix + test regression ở ai-router.
    # Khi route: api_key = AIROUTER_INTERNAL_TOKEN; `model` gửi đi = CAPABILITY name (router
    # tự chọn model thật). KHÔNG route: `model` = tên model thật bên dưới.
    openai_base_url: str | None = None
    # Token nội bộ gửi cho ai-router (Bearer) khi route. TÁCH khỏi openai_api_key để client
    # direct CHƯA migrate (intent/guardrail dùng responses.create) vẫn gọi thẳng OpenAI bằng
    # key thật, còn adapter routed gửi token -> router auth ON không làm gãy 2 client kia.
    # Rỗng (auth router off, vd e2e) -> fallback openai_api_key (router bỏ qua Bearer).
    airouter_internal_token: str | None = None
    # Adapter LangGraph: "responses" (cũ, OpenAI-only) | "chat" (chuẩn, route được qua router).
    # Default "responses" -> prod KHÔNG đổi cho tới khi parity test xanh + bật "chat" có chủ đích.
    llm_model_adapter: str = "responses"
    # Capability name gửi khi route qua ai-router (chỉ dùng khi openai_base_url set).
    llm_capability: str = "think"          # câu trả lời chính: think (gpt-5.4-nano, fallback deepseek)
    intent_capability: str = "triage"      # phân loại nhanh
    guardrail_capability: str = "guardrail"

    mcp_mode: str = "mock"
    mcp_service_url: str = "http://localhost:8003"
    mcp_timeout_seconds: int = 10
    mcp_internal_token: str | None = None
    mcp_circuit_fail_max: int = 5
    mcp_circuit_reset_timeout_seconds: int = 30
    mcp_tool_cache_ttl_seconds: int = 300  # cache MCP tool list 5 min; 0 = off
    tool_routing_mode: str = "legacy"  # "legacy" = typed methods; "native" = generic call_tool

    # hr-service (Leave WRITE REST path): query-service xác thực JWT -> inject user_id ->
    # gọi hr-service bằng X-Internal-Token (PHẢI = HR_INTERNAL_TOKEN của hr-service).
    hr_service_url: str = "http://localhost:8004"
    hr_internal_token: str | None = None
    hr_http_timeout_seconds: float = 10.0

    nats_mode: str = "mock"
    nats_url: str = "nats://localhost:4222"
    nats_jetstream_enabled: bool = True

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "rag_chatbot"

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "http://localhost:3100"

    # LangSmith — chạy SONG SONG langfuse (OBSERVABILITY_MODE=langfuse,langsmith). Low-level
    # RunTree, KHÔNG callback. EU: https://eu.api.smith.langchain.com.
    langsmith_api_key: str | None = None
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "rag-query"

    # Model-price catalog -> tự tính cost gửi vào Langfuse generation (Langfuse self-host
    # v2 không có sẵn pricing model mới). Runtime CHỈ đọc model_prices.json (TOÀN BỘ
    # dataset OpenRouter) đã bundle vào image lúc build (builder stage refresh từ HF; HF
    # lỗi -> giữ bộ dataset cũ đã commit). Không hf/pyarrow ở runtime.
    # override_path: file tuỳ chọn (vd trên volume) ĐÈ bản bundle -> cập nhật giá nóng.
    model_price_enabled: bool = True
    model_price_path: str = "/app/app/infrastructure/observability/data/model_prices.json"
    model_price_override_path: str | None = None

    guardrails_mode: str = "off"  # off | llm_api (LLM-judge injection + regex PII)
    # Model dùng cho LLM-judge guardrail; rỗng -> dùng openai_llm_model. Có thể trỏ model
    # rẻ (gpt-5.4-mini/nano) vì việc phân loại injection nhẹ. Gọi qua provider sẵn có,
    # KHÔNG nhúng model vào container -> không torch.
    guardrail_model: str | None = None
    observability_mode: str = "off"

    allowed_origins: str = Field(
        default="http://localhost:3000,http://localhost:3001",
        validation_alias=AliasChoices("CORS_ORIGINS", "ALLOWED_ORIGINS"),
    )

    semantic_cache_ttl_seconds: int = 3600
    semantic_cache_threshold: float = 0.90
    rag_result_limit: int = 3
    rag_top_k: int = 8  # số chunk tối đa mỗi lần gọi rag_search (LangGraph path)
    rag_score_threshold: float = 0.75  # cosine threshold để show citations cho user
    llm_max_output_tokens: int = 1500
    rag_context_max_chars: int = 10000
    query_rate_limit_per_minute: int = 20
    query_rate_limit_per_ip_per_minute: int = 60  # 1 IP gom nhiều user; > per-user
    query_rate_limit_global_per_minute: int = 600  # trần tổng toàn service
    query_max_concurrent_per_user: int = 3  # số SSE/LLM stream chạy song song / user
    rate_limiter_mode: str = "memory"
    notification_keepalive_seconds: int = 25
    nats_processed_event_max_size: int = 10000
    nats_processed_event_ttl_seconds: int = 86400

    intent_classifier_mode: str = "hybrid"
    intent_rule_confidence_threshold: float = 0.90
    intent_embedding_confidence_threshold: float = 0.78
    intent_embedding_margin: float = 0.08
    intent_llm_confidence_threshold: float = 0.70
    intent_llm_model: str = "gpt-4o-mini"
    intent_llm_timeout_seconds: int = 5

    enable_dev_endpoints: bool = Field(default=False)

    agent_mode: str = "guarded"
    agent_max_iterations: int = 3

    use_langgraph: bool = True  # LangGraph is the canonical agent; set to false to use legacy orchestration

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_runtime_config(self) -> "Settings":
        auth_mode = self.auth_mode.strip().lower()
        app_env = self.app_env.strip().lower()

        if auth_mode == "jwt" and _is_weak_jwt_secret(self.jwt_secret_key):
            raise ValueError("JWT_SECRET_KEY must be set to a strong shared secret when AUTH_MODE=jwt")

        if app_env == "production":
            if self.enable_dev_endpoints:
                raise ValueError("ENABLE_DEV_ENDPOINTS must be false in production")
            mock_modes = {
                "AUTH_MODE": auth_mode,
                "MCP_MODE": self.mcp_mode.strip().lower(),
                "NATS_MODE": self.nats_mode.strip().lower(),
                "LLM_MODE": self.llm_mode.strip().lower(),
            }
            for name, value in mock_modes.items():
                if value == "mock":
                    raise ValueError(f"{name}=mock is not allowed in production")
            if self.rate_limiter_mode.strip().lower() != "redis":
                raise ValueError("RATE_LIMITER_MODE=redis is required in production")

        # Cơ chế LINH HOẠT (mọi môi trường): tích hợp tùy chọn (observability/guardrails)
        # chỉ bật khi có đủ thông tin; thiếu -> tự bỏ backend đó thay vì crash. Trước đây
        # production BẮT BUỘC llm_guard + langfuse -> không có key Langfuse là service không boot.
        # Nay OBSERVABILITY_MODE là danh sách (langfuse,langsmith); lọc backend thiếu key.
        backends = self.observability_backends
        kept: list[str] = []
        if "langfuse" in backends and self.langfuse_public_key and self.langfuse_secret_key:
            kept.append("langfuse")
        if "langsmith" in backends and self.langsmith_api_key:
            kept.append("langsmith")
        self.observability_mode = ",".join(kept) if kept else "off"

        return self

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def observability_backends(self) -> set[str]:
        """OBSERVABILITY_MODE -> set backend (langfuse/langsmith); 'off'/rỗng -> set rỗng."""
        raw = self.observability_mode.strip().lower().replace(";", ",")
        return {b.strip() for b in raw.split(",") if b.strip() and b.strip() != "off"}


def _is_weak_jwt_secret(secret: str | None) -> bool:
    if not secret:
        return True
    stripped = secret.strip()
    return stripped == "your-secret-key-change-in-production" or len(stripped) < 32


@lru_cache
def get_settings() -> Settings:
    return Settings()
