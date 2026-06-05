from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from sqlalchemy import literal, select

from app.core.config import get_settings
from app.infrastructure.db.session import engine
from app.infrastructure.messaging.nats_publisher import NatsPublisher
from app.infrastructure.messaging.nats_subscriber import start_status_subscriber
from app.interfaces.api.routers import documents


settings = get_settings()
app = FastAPI(title=settings.app_name)
app.include_router(documents.router)


@app.on_event("startup")
async def startup() -> None:
    app.state.nats_status_subscriber = await start_status_subscriber(settings)


@app.on_event("shutdown")
async def shutdown() -> None:
    subscriber = getattr(app.state, "nats_status_subscriber", None)
    if subscriber is not None:
        await subscriber.close()


@app.get("/health")
async def health() -> JSONResponse:
    degraded_reasons: list[str] = []
    try:
        async with engine.connect() as connection:
            await connection.execute(select(literal(1)))
    except Exception:
        degraded_reasons.append("database unreachable")

    nats_ok = await NatsPublisher(settings).health_check()
    if not nats_ok:
        degraded_reasons.append("nats unreachable")

    if degraded_reasons:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "degraded",
                "database": "ok" if "database unreachable" not in degraded_reasons else "unreachable",
                "nats": "ok" if "nats unreachable" not in degraded_reasons else "unreachable",
                "degraded_reasons": degraded_reasons,
            },
        )
    return JSONResponse(content={"status": "ok", "database": "ok", "nats": "ok"})

