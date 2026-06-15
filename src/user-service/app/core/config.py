from functools import lru_cache
from os import getenv

from dotenv import load_dotenv
from pydantic import BaseModel


load_dotenv()


class Settings(BaseModel):
    app_name: str = "user-service"
    database_url: str = getenv(
        "USER_SERVICE_DATABASE_URL",
        getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://user:password@localhost:5432/rag_chatbot",
        ),
    )
    jwt_secret_key: str = getenv("JWT_SECRET_KEY", "change-me-in-env")
    nats_url: str = getenv("NATS_URL", "nats://localhost:4222")
    nats_jetstream_enabled: bool = getenv("NATS_JETSTREAM_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    # Phát event vòng đời user (user.created/updated/deactivated) cho hr-service đồng bộ.
    # Best-effort: lỗi publish không làm hỏng nghiệp vụ. Bật mặc định.
    user_events_enabled: bool = getenv("USER_EVENTS_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    access_token_ttl_minutes: int = int(getenv("ACCESS_TOKEN_TTL_MINUTES", "15"))
    refresh_token_ttl_days: int = int(getenv("REFRESH_TOKEN_TTL_DAYS", "7"))
    failed_login_threshold: int = int(getenv("FAILED_LOGIN_THRESHOLD", "5"))
    lockout_minutes: int = int(getenv("LOCKOUT_MINUTES", "15"))
    cookie_secure: bool = getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"}
    allowed_origins: str = getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:3001"
    )

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()
        ]

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        _validate_jwt_secret(self.jwt_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _validate_jwt_secret(secret: str) -> None:
    weak_defaults = {
        "",
        "change-me-in-env",
        "your-secret-key-change-in-production",
    }
    if secret.strip() in weak_defaults:
        raise ValueError("JWT_SECRET_KEY must be set to a strong non-default value")