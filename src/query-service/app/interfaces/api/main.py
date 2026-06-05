from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.infrastructure.config import get_settings
from app.interfaces.api.dependencies import get_nats_subscriber_manager
from app.interfaces.api.routers import admin, conversations, feedback, notifications, query


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = get_nats_subscriber_manager()
    if manager is not None:
        await manager.start()
    try:
        yield
    finally:
        if manager is not None:
            await manager.stop()


app = FastAPI(
    title="Query Service",
    version="0.1.0-phase1",
    description="LLM orchestration, MCP client mock, SSE, conversations, feedback, and notifications.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query.router)
app.include_router(notifications.router)
app.include_router(conversations.router)
app.include_router(feedback.router)
app.include_router(admin.router)


@app.get("/health")
async def health() -> dict:
    degraded_reasons: list[str] = []
    if settings.llm_mode == "openai" and not settings.openai_api_key:
        degraded_reasons.append("OPENAI_API_KEY missing while LLM_MODE=openai")
    status = "degraded" if degraded_reasons else "ok"
    return {
        "status": status,
        "database": "mock",
        "mcp_service": settings.mcp_mode,
        "nats": settings.nats_mode,
        "auth": settings.auth_mode,
        "llm": settings.llm_mode,
        "degraded_reasons": degraded_reasons,
    }
