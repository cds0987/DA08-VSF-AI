from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import load_settings


def create_app() -> FastAPI:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = FastAPI(title="hr-service")
    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = load_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
