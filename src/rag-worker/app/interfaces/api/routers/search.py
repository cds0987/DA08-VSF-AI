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
        payload.query_text,
        document_ids=payload.document_ids,
        top_k=payload.top_k,
        correlation_id=payload.correlation_id,
    )
    return SearchResponse(
        results=[
            SearchResultResponse(
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                document_name=result.document_name,
                caption=result.caption,
                parent_text=result.parent_text,
                heading_path=result.heading_path,
                score=result.score,
                page_number=result.page_number,
                source_s3_uri=result.lineage.source_uri,
                markdown_s3_uri=result.lineage.artifact_uri,
            )
            for result in results
        ]
    )
