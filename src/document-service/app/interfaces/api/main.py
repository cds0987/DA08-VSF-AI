from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import literal, select

from app.core.config import get_settings
from app.infrastructure.db.session import engine
from app.infrastructure.messaging.nats_publisher import NatsPublisher
from app.infrastructure.messaging.nats_subscriber import start_status_subscriber
from app.interfaces.api.routers import documents


settings = get_settings()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)


@app.on_event("startup")
async def startup() -> None:
    app.state.nats_publisher = NatsPublisher(settings)
    app.state.nats_status_subscriber = await start_status_subscriber(
        settings,
        app.state.nats_publisher,
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    subscriber = getattr(app.state, "nats_status_subscriber", None)
    if subscriber is not None:
        await subscriber.close()
    publisher = getattr(app.state, "nats_publisher", None)
    if publisher is not None:
        await publisher.close()


@app.get("/health")
async def health() -> JSONResponse:
    degraded_reasons: list[str] = []
    try:
        async with engine.connect() as connection:
            await connection.execute(select(literal(1)))
    except Exception:
        degraded_reasons.append("database unreachable")

    publisher = getattr(app.state, "nats_publisher", None)
    if publisher is None:
        publisher = NatsPublisher(settings)
    nats_ok = await publisher.health_check()
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

