from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.interfaces.api.routers import ingest, search
from app.interfaces.api.runtime import lifespan


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Service", lifespan=lifespan)
    app.include_router(ingest.router, prefix="/api", tags=["ingest"])
    app.include_router(search.router, prefix="/api", tags=["search"])

    @app.get("/health")
    async def healthcheck():
        report = app.state.health
        status_code = 200 if report.status == "healthy" else 503
        return JSONResponse(status_code=status_code, content=report.to_dict())

    return app


app = create_app()
