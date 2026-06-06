from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import literal, select

from app.core.config import get_settings
from app.infrastructure.db.session import engine
from app.interfaces.api.routers import auth, users


settings = get_settings()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)


@app.get("/health")
async def health() -> JSONResponse:
    try:
        async with engine.connect() as connection:
            await connection.execute(select(literal(1)))
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "degraded",
                "degraded_reasons": ["database unreachable"],
            },
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})

