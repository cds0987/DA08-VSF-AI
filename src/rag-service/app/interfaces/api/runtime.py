from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from typing import AsyncIterator

from fastapi import FastAPI

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.application.use_cases.query import RetrievalUseCase
from app.domain.repositories.document_repository import DocumentRepository
from app.infrastructure.db import InMemoryDocumentRepository
from haystack_interface.ai import get_ai_provider, load_ai_settings, reset_ai_provider
from haystack_interface.config import load_settings
from haystack_interface.factory import build_engine
from haystack_interface.logging_utils import log_event
from haystack_interface.vectorstore import VectorStoreConfig, available_providers


def _is_production(app_env: str) -> bool:
    return app_env.lower() in {"prod", "production"}


@dataclass
class HealthReport:
    status: str
    app_env: str
    ai_provider: str
    vector_provider: str
    vector_deployment: str
    vector_index: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RuntimeState:
    ingest_use_case: IngestDocumentUseCase | None
    retrieval_use_case: RetrievalUseCase | None
    health: HealthReport


def validate_runtime_settings() -> None:
    settings = load_settings()
    if settings.embed_dimension <= 0:
        raise ValueError("EMBED_DIMENSION must be > 0")
    if settings.top_k_candidates <= 0:
        raise ValueError("SEARCH_TOP_K must be > 0")
    if settings.rerank_top_k <= 0:
        raise ValueError("RERANK_TOP_K must be > 0")
    if settings.top_k_candidates < settings.rerank_top_k:
        raise ValueError("SEARCH_TOP_K must be >= RERANK_TOP_K")


def validate_vector_config(vector_config: VectorStoreConfig) -> None:
    if not vector_config.collection.strip():
        raise ValueError("VECTOR_COLLECTION must not be empty")
    if vector_config.provider.lower() not in available_providers():
        raise ValueError(
            f"VECTOR_DB_PROVIDER {vector_config.provider!r} is not registered"
        )
    if vector_config.dimension <= 0:
        raise ValueError("Vector store dimension must be > 0")
    if vector_config.deployment == "remote" and not vector_config.url.strip():
        raise ValueError("VECTOR_DB_URL must not be empty for remote vector deployment")


def bootstrap_runtime() -> RuntimeState:
    logger = logging.getLogger(__name__)
    app_env = os.getenv("APP_ENV", "development")
    validate_runtime_settings()
    ai_settings = load_ai_settings()
    vector_config = VectorStoreConfig.from_env()
    validate_vector_config(vector_config)

    reset_ai_provider()
    provider = get_ai_provider()

    reasons: list[str] = []
    if provider.name == "offline":
        reasons.append("AI provider is offline.")
    if vector_config.deployment != "remote":
        reasons.append("Vector backend is running in_process.")
    if ai_settings.embed_dimension and ai_settings.embed_dimension != vector_config.dimension:
        reasons.append("Vector dimension differs from embed dimension before engine wiring.")

    if _is_production(app_env) and reasons:
        log_event(
            logger,
            logging.ERROR,
            "runtime_fail_closed",
            stage="startup",
            app_env=app_env,
            reasons=reasons,
        )
        raise RuntimeError("Production fail-closed: " + " ".join(reasons))

    ingest_use_case = None
    retrieval_use_case = None
    try:
        engine = build_engine(provider=provider, vector_config=vector_config)
        document_repository = build_document_repository()
        ingest_use_case = IngestDocumentUseCase(engine, document_repository)
        retrieval_use_case = RetrievalUseCase(engine)
    except Exception as exc:
        reasons.append(f"Engine bootstrap failed: {exc}")
        if _is_production(app_env):
            raise

    health = HealthReport(
        status="healthy" if not reasons else "unhealthy",
        app_env=app_env,
        ai_provider=provider.name,
        vector_provider=vector_config.provider,
        vector_deployment=vector_config.deployment,
        vector_index=vector_config.index_id(),
        reasons=reasons,
    )
    log_event(
        logger,
        logging.INFO,
        "runtime_bootstrap",
        stage="startup",
        app_env=app_env,
        status=health.status,
        ai_provider=provider.name,
        vector_provider=vector_config.provider,
        vector_deployment=vector_config.deployment,
    )
    return RuntimeState(
        ingest_use_case=ingest_use_case,
        retrieval_use_case=retrieval_use_case,
        health=health,
    )


def build_document_repository() -> DocumentRepository:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return InMemoryDocumentRepository()
    from app.infrastructure.db import PostgresDocumentRepository

    return PostgresDocumentRepository(database_url)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime = bootstrap_runtime()
    app.state.ingest_use_case = runtime.ingest_use_case
    app.state.retrieval_use_case = runtime.retrieval_use_case
    app.state.health = runtime.health
    yield
