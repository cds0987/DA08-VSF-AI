from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str
    mcp_service: str
    mcp_circuit: str
    nats: str
    auth: str
    llm: str
    degraded_reasons: list[str]

from app.infrastructure.config import get_settings
from app.interfaces.api.dependencies import (
    get_langchain_mcp_tools_loader,
    get_mcp_client,
    get_nats_subscriber_manager,
    get_rate_limiter,
    get_document_access_repo,
)
from app.interfaces.api.routers import admin, conversations, feedback, notifications, query
from app.infrastructure.logging_utils import configure_logging


settings = get_settings()

# Bật JSON logging ra stdout NGAY khi import (trước khi node nào chạy) — để
# langgraph_act/think (intent, tool) hiện trên docker logs. Trước đây root logger
# mặc định WARNING -> mọi INFO bị nuốt, không soi được luồng agent.
import logging as _logging

configure_logging(getattr(_logging, str(getattr(settings, "log_level", "INFO")).upper(), _logging.INFO))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migrate schema query_svc lúc khởi động (idempotent). Non-fatal để container vẫn
    # đứng được cho việc chẩn đoán nếu DB lỗi, thay vì crash-loop.
    if settings.database_url:
        import logging

        from app.infrastructure.db.migrate import run_migrations

        try:
            await run_migrations(settings.database_url)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).error("query-service migration failed: %s", exc)

    manager = get_nats_subscriber_manager()
    if manager is not None:
        await manager.start()

    tools_loader = get_langchain_mcp_tools_loader()
    if tools_loader is not None:
        await tools_loader.warmup()

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


@app.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
async def health():
    current_settings = get_settings()
    degraded_reasons: list[str] = []

    # --- LLM config check ---
    if current_settings.llm_mode == "openai" and not current_settings.openai_api_key:
        degraded_reasons.append("OPENAI_API_KEY missing while LLM_MODE=openai")
    if current_settings.nats_mode == "nats" and not current_settings.database_url:
        degraded_reasons.append("DATABASE_URL missing while NATS_MODE=nats")

    # --- Circuit breaker status ---
    mcp_client = get_mcp_client()
    circuit_open: bool = bool(getattr(mcp_client, "is_circuit_open", False))
    mcp_circuit = "open" if circuit_open else "closed"
    if circuit_open:
        degraded_reasons.append("MCP circuit breaker is open")

    # --- DB liveness ping (best-effort, short timeout) ---
    db_status = "configured" if current_settings.database_url else "mock"
    if current_settings.database_url:
        try:
            repo = get_document_access_repo()
            pool = await repo._get_pool()  # type: ignore[attr-defined]
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
        except Exception as exc:
            db_status = "unreachable"
            degraded_reasons.append(f"database unreachable: {exc}")

    # --- Redis liveness ping (best-effort) ---
    redis_mode = current_settings.rate_limiter_mode.strip().lower()
    redis_status = "configured" if redis_mode == "redis" else "memory"
    if redis_mode == "redis":
        try:
            limiter = get_rate_limiter()
            ping = getattr(limiter, "ping", None)
            if callable(ping):
                await ping()
        except Exception as exc:
            redis_status = "unreachable"
            degraded_reasons.append(f"redis unreachable: {exc}")

    status = "degraded" if degraded_reasons else "ok"
    body = {
        "status": status,
        "database": db_status,
        "redis": redis_status,
        "mcp_service": current_settings.mcp_mode,
        "mcp_circuit": mcp_circuit,
        "nats": current_settings.nats_mode,
        "auth": current_settings.auth_mode,
        "llm": current_settings.llm_mode,
        "degraded_reasons": degraded_reasons,
    }
    return JSONResponse(
        status_code=503 if degraded_reasons else 200,
        content=body,
    )
