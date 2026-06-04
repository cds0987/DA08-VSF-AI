from fastapi import APIRouter, Depends

from app.application.use_cases.query import RetrievalUseCase
from app.interfaces.api.dependencies import get_retrieval_use_case
from app.interfaces.api.schemas.search import (
    SearchRequest,
    SearchResponse,
    SearchResultResponse,
)

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
async def search_documents(
    payload: SearchRequest,
    use_case: RetrievalUseCase = Depends(get_retrieval_use_case),
) -> SearchResponse:
    results = await use_case.execute(
        payload.question,
        correlation_id=payload.correlation_id,
    )
    return SearchResponse(
        results=[
            SearchResultResponse.model_validate(result, from_attributes=True)
            for result in results
        ]
    )
