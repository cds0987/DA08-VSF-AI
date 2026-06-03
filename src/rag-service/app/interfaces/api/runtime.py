from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from typing import AsyncIterator

from fastapi import FastAPI

from app.application.use_cases.query import RetrievalUseCase
from haystack_interface.ai import get_ai_provider, load_ai_settings, reset_ai_provider
from haystack_interface.factory import build_engine
from haystack_interface.vectorstore import VectorStoreConfig


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
    retrieval_use_case: RetrievalUseCase | None
    health: HealthReport


def bootstrap_runtime() -> RuntimeState:
    app_env = os.getenv("APP_ENV", "development")
    ai_settings = load_ai_settings()
    vector_config = VectorStoreConfig.from_env()

    reset_ai_provider()
    provider = get_ai_provider()

    reasons: list[str] = []
    if provider.name == "offline":
        reasons.append("AI provider is offline.")
    if vector_config.deployment != "remote":
        reasons.append("Vector backend is running in_process.")

    if _is_production(app_env) and reasons:
        raise RuntimeError(
            "Production fail-closed: " + " ".join(reasons)
        )

    retrieval_use_case = None
    try:
        engine = build_engine(provider=provider, vector_config=vector_config)
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
    return RuntimeState(retrieval_use_case=retrieval_use_case, health=health)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime = bootstrap_runtime()
    app.state.retrieval_use_case = runtime.retrieval_use_case
    app.state.health = runtime.health
    yield
