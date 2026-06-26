from fastapi import APIRouter, Depends

from app.application.use_cases.search import SearchUseCase
from app.interfaces.api.dependencies import get_search_use_case
from app.interfaces.api.schemas.search import (
    SearchCandidateResponse,
    SearchRequest,
    SearchResponse,
)

router = APIRouter()

# Query-side retrieval chuyển từ mcp-service về rag-worker. Endpoint trả ứng viên
# (CHƯA rerank) cho caller. ACL nằm ở document_ids (rỗng/None -> kết quả rỗng).


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    use_case: SearchUseCase = Depends(get_search_use_case),
) -> SearchResponse:
    candidates = await use_case.search(
        query=payload.query,
        document_ids=payload.document_ids,
        top_k=payload.top_k,
    )
    return SearchResponse(
        candidates=[
            SearchCandidateResponse(
                chunk_id=candidate.chunk_id,
                document_id=candidate.document_id,
                document_name=candidate.document_name,
                caption=candidate.caption,
                child_text=candidate.child_text,
                parent_text=candidate.parent_text,
                heading_path=candidate.heading_path,
                score=candidate.score,
                page_number=candidate.page_number,
                source_gcs_uri=candidate.source_gcs_uri,
                markdown_gcs_uri=candidate.markdown_gcs_uri,
            )
            for candidate in candidates
        ]
    )
