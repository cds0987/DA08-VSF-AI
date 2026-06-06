from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
async def health():
    current_settings = get_settings()
    degraded_reasons: list[str] = []
    if current_settings.llm_mode == "openai" and not current_settings.openai_api_key:
        degraded_reasons.append("OPENAI_API_KEY missing while LLM_MODE=openai")
    if current_settings.nats_mode == "nats" and not current_settings.database_url:
        degraded_reasons.append("DATABASE_URL missing while NATS_MODE=nats")
    status = "degraded" if degraded_reasons else "ok"
    body = {
        "status": status,
        "database": "configured" if current_settings.database_url else "mock",
        "redis": "configured"
        if current_settings.rate_limiter_mode.strip().lower() == "redis"
        else "memory",
        "mcp_service": current_settings.mcp_mode,
        "nats": current_settings.nats_mode,
        "auth": current_settings.auth_mode,
        "llm": current_settings.llm_mode,
        "degraded_reasons": degraded_reasons,
    }
    return JSONResponse(
        status_code=503 if degraded_reasons else 200,
        content=body,
    )
