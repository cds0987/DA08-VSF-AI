from functools import lru_cache
from os import getenv

from dotenv import load_dotenv
from pydantic import BaseModel


load_dotenv()


class Settings(BaseModel):
    app_name: str = "document-service"
    database_url: str = getenv(
        "DOCUMENT_SERVICE_DATABASE_URL",
        getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/doc_db",
        ),
    )
    jwt_secret_key: str = getenv("JWT_SECRET_KEY", "change-me-in-env")
    jwt_algorithm: str = getenv("JWT_ALGORITHM", "HS256")
    nats_url: str = getenv("NATS_URL", "nats://localhost:4222")
    nats_jetstream_enabled: bool = getenv("NATS_JETSTREAM_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    gcs_bucket: str = getenv("GCS_BUCKET", "rag-chatbot-docs")
    gcp_project_id: str | None = getenv("GCP_PROJECT_ID")
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
        _validate_jwt_algorithm(self.jwt_algorithm)


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


def _validate_jwt_algorithm(algorithm: str) -> None:
    if algorithm != "HS256":
        raise ValueError("JWT_ALGORITHM must be HS256")

