from __future__ import annotations

import os

from fastapi import Header, HTTPException, Request, status

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.application.use_cases.search import SearchUseCase


def get_ingest_use_case(request: Request) -> IngestDocumentUseCase:
    use_case = getattr(request.app.state, "ingest_use_case", None)
    if use_case is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ingest use case is not configured",
        )
    return use_case


def get_search_use_case(request: Request) -> SearchUseCase:
    use_case = getattr(request.app.state, "search_use_case", None)
    if use_case is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="search use case is not configured",
        )
    return use_case


def require_delete_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    required = os.getenv("INGEST_DELETE_API_KEY", "").strip()
    if not required:
        return
    if x_api_key != required:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid delete API key",
        )
