from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.interfaces.api.dependencies import get_ingest_use_case
from app.interfaces.api.schemas.ingest import DocumentResponse, IngestRequest, IngestResponse

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
        correlation_id=payload.correlation_id,
    )
    return IngestResponse(
        document_id=payload.document_id,
        status="completed",
        chunk_count=chunk_count,
        message="document ingested",
    )


@router.get("/ingest/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    use_case: IngestDocumentUseCase = Depends(get_ingest_use_case),
) -> DocumentResponse:
    document = await use_case.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return DocumentResponse(
        document_id=document.id,
        document_name=document.name,
        file_type=document.file_type,
        source_uri=document.s3_key,
        status=document.status.value,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        error_message=document.error_message,
    )


@router.get("/ingest", response_model=list[DocumentResponse])
async def list_documents(
    use_case: IngestDocumentUseCase = Depends(get_ingest_use_case),
) -> list[DocumentResponse]:
    documents = await use_case.list_documents()
    return [
        DocumentResponse(
            document_id=document.id,
            document_name=document.name,
            file_type=document.file_type,
            source_uri=document.s3_key,
            status=document.status.value,
            chunk_count=document.chunk_count,
            created_at=document.created_at,
            error_message=document.error_message,
        )
        for document in documents
    ]


@router.delete("/ingest/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    use_case: IngestDocumentUseCase = Depends(get_ingest_use_case),
) -> Response:
    await use_case.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
