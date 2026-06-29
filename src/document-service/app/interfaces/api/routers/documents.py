from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response

from app.application.auth import CurrentUser
from app.application.exceptions import (
    MessagingPublishError,
    NotFoundError,
    PermissionDeniedError,
    StorageError,
    ValidationError,
)
from app.application.use_cases.documents.common import ALLOWED_EXTENSIONS, MAX_FILE_BYTES
from app.application.use_cases.documents.bulk_delete_documents_use_case import (
    BulkDeleteDocumentsUseCase,
)
from app.application.use_cases.documents.delete_document_use_case import DeleteDocumentUseCase
from app.application.use_cases.documents.get_document_file_preview_use_case import (
    GetDocumentFilePreviewUseCase,
)
from app.application.use_cases.documents.get_document_file_stream_use_case import (
    GetDocumentFileStreamUseCase,
)
from app.application.use_cases.documents.get_document_file_use_case import GetDocumentFileUseCase
from app.application.use_cases.documents.get_document_use_case import GetDocumentUseCase
from app.application.use_cases.documents.list_documents_use_case import ListDocumentsUseCase
from app.application.use_cases.documents.upload_document_use_case import UploadDocumentUseCase
from app.domain.entities.document import Document, DocumentStatus
from app.infrastructure.db.models import AuditLogModel
from app.infrastructure.db.postgres_audit_log_repository import PostgresAuditLogRepository
from app.interfaces.api.dependencies import (
    get_audit_logger,
    get_current_user,
    get_bulk_delete_documents_use_case,
    get_delete_document_use_case,
    get_get_document_file_preview_use_case,
    get_get_document_file_stream_use_case,
    get_get_document_file_use_case,
    get_get_document_use_case,
    get_list_documents_use_case,
    get_upload_document_use_case,
    require_admin,
)
from app.interfaces.api.schemas.audit import AuditLogItem, AuditLogList
from app.interfaces.api.schemas.document import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    DocumentDetail,
    DocumentFileResponse,
    DocumentItem,
    DocumentList,
    MessageResponse,
    SupportedFormatsResponse,
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


@router.get("/supported-formats", response_model=SupportedFormatsResponse)
async def supported_formats(
    actor: CurrentUser = Depends(require_admin),
) -> SupportedFormatsResponse:
    # Nguồn cho frontend dựng accept/validation. = ALLOWED_EXTENSIONS (manifest
    # rag-worker ∩ allow_list chính sách) -> FE không bao giờ lệch backend.
    del actor
    return SupportedFormatsResponse(
        extensions=sorted(ALLOWED_EXTENSIONS),
        max_file_bytes=MAX_FILE_BYTES,
    )


# PHẢI khai báo TRƯỚC "/{document_id}" — nếu không "/documents/audit-logs" sẽ khớp
# nhầm vào /{document_id} (document_id="audit-logs") -> parse UUID fail -> 500.
@router.get("/audit-logs", response_model=AuditLogList)
async def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: CurrentUser = Depends(require_admin),
    repo: PostgresAuditLogRepository = Depends(get_audit_logger),
) -> AuditLogList:
    rows, total = await repo.list(limit=limit, offset=offset)
    return AuditLogList(items=[_to_audit_item(row) for row in rows], total=total)


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: str,
    actor: CurrentUser = Depends(get_current_user),
    use_case: GetDocumentUseCase = Depends(get_get_document_use_case),
) -> DocumentDetail:
    try:
        document = await use_case.execute(actor, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc) or "Khong co quyen xem tai lieu nay",
        ) from exc
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
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.detail,
        ) from exc
    return DocumentFileResponse(
        url=result.url,
        file_type=result.file_type,
        expires_in=result.expires_in,
    )


@router.get("/{document_id}/file/preview")
async def get_document_file_preview(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    use_case: GetDocumentFilePreviewUseCase = Depends(get_get_document_file_preview_use_case),
) -> Response:
    """Nội dung render-được inline trong viewer (giữ URL /admin/documents/{id}).

    Native (pdf/ảnh/txt/md) passthrough; office (docx/pptx) convert sang PDF qua Gotenberg
    (cache GCS previews/). Gotenberg lỗi/timeout -> 503 (FE hiện error card: Thử lại + Tải gốc).
    """
    try:
        result = await use_case.execute(user, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc) or "Khong co quyen xem tai lieu nay",
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.detail,
        ) from exc

    ascii_name = result.filename.encode("ascii", "ignore").decode("ascii") or "document"
    disposition = (
        f"inline; filename=\"{ascii_name}\"; "
        f"filename*=UTF-8''{quote(result.filename)}"
    )
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{document_id}/file/raw")
async def get_document_file_raw(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    use_case: GetDocumentFileStreamUseCase = Depends(get_get_document_file_stream_use_case),
) -> Response:
    """Proxy-stream nội dung file qua domain mình (KHÔNG trả presigned-URL GCS).

    Giữ ACL per-request + không đẩy tài liệu sang officeapps/google. FE fetch endpoint này
    dạng blob rồi mở object-URL -> tab hiển thị blob:https://vsfchat..., PDF render inline.
    """
    try:
        result = await use_case.execute(user, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc) or "Khong co quyen xem tai lieu nay",
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.detail,
        ) from exc

    # RFC 5987: filename* cho tên unicode (tiếng Việt), filename ascii làm fallback.
    ascii_name = result.filename.encode("ascii", "ignore").decode("ascii") or "document"
    disposition = (
        f"{result.disposition}; filename=\"{ascii_name}\"; "
        f"filename*=UTF-8''{quote(result.filename)}"
    )
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_documents(
    payload: BulkDeleteRequest,
    request: Request,
    actor: CurrentUser = Depends(require_admin),
    use_case: BulkDeleteDocumentsUseCase = Depends(get_bulk_delete_documents_use_case),
) -> BulkDeleteResponse:
    result = await use_case.execute(
        actor=actor,
        document_ids=payload.document_ids,
        ip_address=request.client.host if request.client else None,
    )
    return BulkDeleteResponse(
        deleted=result.deleted,
        not_found=result.not_found,
        failed=result.failed,
        message=result.message,
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


def _to_audit_item(row: AuditLogModel) -> AuditLogItem:
    return AuditLogItem(
        id=str(row.id),
        actor_id=str(row.actor_id),
        actor_role=row.actor_role,
        action=row.action,
        resource_type=row.resource_type,
        resource_id=str(row.resource_id) if row.resource_id else None,
        detail=row.detail,
        ip_address=row.ip_address,
        created_at=row.created_at.isoformat(),
    )
