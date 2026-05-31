from fastapi import FastAPI
from app.interfaces.api.routers import auth

app = FastAPI(title="User Service")
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
