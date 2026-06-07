from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.interfaces.api.dependencies import get_ingest_use_case, require_delete_api_key
from app.interfaces.api.schemas.ingest import (
    DocumentResponse,
    IngestJobResponse,
)

router = APIRouter()

# Tạo ingest đã chuyển sang NATS (subject doc.ingest) — không còn POST /ingest.
# Các endpoint dưới chỉ ĐỌC/quản lý trạng thái tài liệu + job.


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


@router.get("/ingest/jobs/{job_id}", response_model=IngestJobResponse)
async def get_ingest_job(
    job_id: str,
    use_case: IngestDocumentUseCase = Depends(get_ingest_use_case),
) -> IngestJobResponse:
    job = await use_case.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return IngestJobResponse(
        job_id=job.id,
        document_id=job.document_id,
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        claim_id=job.claim_id,
        attempt=job.attempt,
        chunk_count=job.chunk_count,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
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
    _: None = Depends(require_delete_api_key),
    use_case: IngestDocumentUseCase = Depends(get_ingest_use_case),
) -> Response:
    await use_case.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
