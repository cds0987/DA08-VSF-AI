from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.application.use_cases.query import RetrievalUseCase


def get_retrieval_use_case(request: Request) -> RetrievalUseCase:
    use_case = getattr(request.app.state, "retrieval_use_case", None)
    if use_case is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="retrieval use case is not configured",
        )
    return use_case
