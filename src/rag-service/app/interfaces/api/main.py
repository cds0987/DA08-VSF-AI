from fastapi import FastAPI
from app.interfaces.api.routers import ingest, search

app = FastAPI(title="RAG Service")
app.include_router(ingest.router, prefix="/api", tags=["ingest"])
app.include_router(search.router, prefix="/api", tags=["search"])
