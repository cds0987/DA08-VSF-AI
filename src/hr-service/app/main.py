from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import load_settings


def create_app() -> FastAPI:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.infrastructure.db.postgres_hr_repository import PostgresHrRepository
        from app.infrastructure.user_events_subscriber import start_user_events_subscriber

        handle = await start_user_events_subscriber(
            settings,
            repo_factory=lambda: PostgresHrRepository(settings.database_url),
        )
        try:
            yield
        finally:
            await handle.close()

    app = FastAPI(title="hr-service", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = load_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
