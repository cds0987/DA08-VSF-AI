from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from app.application.auth import CurrentUser
from app.application.exceptions import (
    MessagingPublishError,
    NotFoundError,
    PermissionDeniedError,
    StorageError,
    ValidationError,
)
from app.application.use_cases.documents.delete_document_use_case import DeleteDocumentUseCase
from app.application.use_cases.documents.get_document_file_use_case import GetDocumentFileUseCase
from app.application.use_cases.documents.get_document_use_case import GetDocumentUseCase
from app.application.use_cases.documents.list_documents_use_case import ListDocumentsUseCase
from app.application.use_cases.documents.upload_document_use_case import UploadDocumentUseCase
from app.domain.entities.document import Document, DocumentStatus
from app.interfaces.api.dependencies import (
    get_current_user,
    get_delete_document_use_case,
    get_get_document_file_use_case,
    get_get_document_use_case,
    get_list_documents_use_case,
    get_upload_document_use_case,
    require_admin,
)
from app.interfaces.api.schemas.document import (
    DocumentDetail,
    DocumentFileResponse,
    DocumentItem,
    DocumentList,
    MessageResponse,
    UploadResponse,
)


router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    classification: str = Form(...),
    allowed_departments: str | None = Form(default=None),
    allowed_user_ids: str | None = Form(default=None),
    actor: CurrentUser = Depends(require_admin),
    use_case: UploadDocumentUseCase = Depends(get_upload_document_use_case),
) -> UploadResponse:
    content = await file.read()
    try:
        result = await use_case.execute(
            actor=actor,
            filename=file.filename or "",
            content=content,
            classification=classification,
            allowed_departments=allowed_departments,
            allowed_user_ids=allowed_user_ids,
            content_type=file.content_type,
            ip_address=request.client.host if request.client else None,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail) from exc
    except MessagingPublishError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.detail,
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.detail,
        ) from exc
    return UploadResponse(
        document_id=result.document_id,
        status=result.status,
        message=result.message,
    )


@router.get("", response_model=DocumentList)
async def list_documents(
    status_filter: DocumentStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: CurrentUser = Depends(require_admin),
    use_case: ListDocumentsUseCase = Depends(get_list_documents_use_case),
) -> DocumentList:
    result = await use_case.execute(
        actor=actor,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return DocumentList(
        items=[_to_item(document) for document in result.items],
        total=result.total,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: str,
    actor: CurrentUser = Depends(require_admin),
    use_case: GetDocumentUseCase = Depends(get_get_document_use_case),
) -> DocumentDetail:
    try:
        document = await use_case.execute(actor, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    return _to_detail(document)


@router.get("/{document_id}/file", response_model=DocumentFileResponse)
async def get_document_file(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    use_case: GetDocumentFileUseCase = Depends(get_get_document_file_use_case),
) -> DocumentFileResponse:
    try:
        result = await use_case.execute(user, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc) or "Khong co quyen xem tai lieu nay",
        ) from exc
    return DocumentFileResponse(
        url=result.url,
        file_type=result.file_type,
        expires_in=result.expires_in,
    )


@router.delete("/{document_id}", response_model=MessageResponse)
async def delete_document(
    document_id: str,
    request: Request,
    actor: CurrentUser = Depends(require_admin),
    use_case: DeleteDocumentUseCase = Depends(get_delete_document_use_case),
) -> MessageResponse:
    try:
        result = await use_case.execute(
            actor=actor,
            document_id=document_id,
            ip_address=request.client.host if request.client else None,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    return MessageResponse(message=result.message)


def _to_item(document: Document) -> DocumentItem:
    return DocumentItem(
        id=document.id,
        name=document.name,
        file_type=document.file_type,
        status=document.status.value,
        classification=document.classification,
        uploaded_by=document.uploaded_by,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
    )


def _to_detail(document: Document) -> DocumentDetail:
    item = _to_item(document)
    return DocumentDetail(
        **item.model_dump(),
        error_message=document.error_message,
        allowed_departments=document.allowed_departments,
        allowed_user_ids=document.allowed_user_ids,
    )
