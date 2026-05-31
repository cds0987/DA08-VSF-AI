from fastapi import FastAPI
from app.interfaces.api.routers import query, documents

app = FastAPI(title="Chat Service")
app.include_router(query.router, prefix="/api", tags=["query"])
app.include_router(documents.router, prefix="/api", tags=["documents"])
