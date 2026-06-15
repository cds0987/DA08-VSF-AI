from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.hr_admin import admin_router
from app.api.routes import public_router, router
from app.core.config import load_settings
from app.core.logging_utils import configure_logging


def create_app() -> FastAPI:
    settings = load_settings()
    # JSON logging ra stdout (đồng nhất rag-worker) thay cho basicConfig text (T3).
    configure_logging(getattr(logging, settings.log_level.upper(), logging.INFO))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.infrastructure.nats_publisher import NatsPublisher
        from app.infrastructure.db.postgres_hr_repository import PostgresHrRepository
        from app.infrastructure.user_events_subscriber import start_user_events_subscriber

        publisher = NatsPublisher(settings)
        # Inject cho routes write (POST /hr/leave-requests ...) qua get_publisher.
        app.state.publisher = publisher
        handle = await start_user_events_subscriber(
            settings,
            repo_factory=lambda: PostgresHrRepository(settings.database_url),
            publisher=publisher,
        )
        try:
            yield
        finally:
            await handle.close()
            await publisher.aclose()
            app.state.publisher = None

    app = FastAPI(title="hr-service", lifespan=lifespan)
    app.include_router(router)
    app.include_router(public_router)
    app.include_router(admin_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = load_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
