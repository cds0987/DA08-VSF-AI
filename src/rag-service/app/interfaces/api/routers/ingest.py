from fastapi import APIRouter, Depends, Response, status

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.interfaces.api.dependencies import get_ingest_use_case
from app.interfaces.api.schemas.ingest import IngestRequest, IngestResponse

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    payload: IngestRequest,
    use_case: IngestDocumentUseCase = Depends(get_ingest_use_case),
) -> IngestResponse:
    chunk_count = await use_case.ingest(
        document_id=payload.document_id,
        document_name=payload.document_name,
        file_type=payload.file_type,
        markdown=payload.markdown,
        source_uri=payload.source_uri,
        artifact_uri=payload.artifact_uri,
    )
    return IngestResponse(
        document_id=payload.document_id,
        status="completed",
        chunk_count=chunk_count,
        message="document ingested",
    )


@router.delete("/ingest/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    use_case: IngestDocumentUseCase = Depends(get_ingest_use_case),
) -> Response:
    await use_case.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
