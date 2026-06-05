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
    aws_access_key_id: str | None = getenv("AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str | None = getenv("AWS_SECRET_ACCESS_KEY")
    aws_s3_bucket: str = getenv("AWS_S3_BUCKET", "rag-chatbot-docs")
    aws_region: str = getenv("AWS_REGION", "ap-southeast-1")


@lru_cache
def get_settings() -> Settings:
    return Settings()

