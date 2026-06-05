from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "query-service"
    database_url: str | None = None

    auth_mode: str = "mock"
    jwt_secret_key: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    user_service_url: str = "http://localhost:8000"
    auth_http_timeout_seconds: float = 5.0

    redis_url: str = "redis://localhost:6379/0"

    llm_mode: str = "openai"
    openai_api_key: str | None = None
    openai_llm_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: int = 30

    mcp_mode: str = "mock"
    mcp_service_url: str = "http://localhost:8003"
    mcp_timeout_seconds: int = 10

    nats_mode: str = "mock"
    nats_url: str = "nats://localhost:4222"
    nats_jetstream_enabled: bool = True

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "rag_chatbot"

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "http://localhost:3100"

    allowed_origins: str = "http://localhost:3000,http://localhost:3001"

    semantic_cache_ttl_seconds: int = 3600
    semantic_cache_threshold: float = 0.95
    rag_score_threshold: float = 0.70
    query_rate_limit_per_minute: int = 20
    notification_keepalive_seconds: int = 25

    intent_classifier_mode: str = "hybrid"
    intent_rule_confidence_threshold: float = 0.90
    intent_embedding_confidence_threshold: float = 0.78
    intent_embedding_margin: float = 0.08
    intent_llm_confidence_threshold: float = 0.70
    intent_llm_model: str = "gpt-4o-mini"
    intent_llm_timeout_seconds: int = 5

    enable_dev_endpoints: bool = Field(default=True)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
