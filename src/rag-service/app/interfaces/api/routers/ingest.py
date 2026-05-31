# TODO: RAG Engineer
# POST /ingest           → IngestDocumentUseCase (Admin upload)
# POST /ingest/approve   → approve + queue (Admin approve End User upload)
# DELETE /ingest/{id}    → delete document + vectors
from fastapi import APIRouter

router = APIRouter()
