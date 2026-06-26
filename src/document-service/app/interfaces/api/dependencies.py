from collections.abc import AsyncGenerator
from functools import lru_cache
import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.auth import CurrentUser
from app.application.exceptions import PermissionDeniedError
from app.application.use_cases.documents.bulk_delete_documents_use_case import (
    BulkDeleteDocumentsUseCase,
)
from app.application.use_cases.documents.delete_document_use_case import DeleteDocumentUseCase
from app.application.use_cases.documents.get_document_file_stream_use_case import (
    GetDocumentFileStreamUseCase,
)
from app.application.use_cases.documents.get_document_file_use_case import GetDocumentFileUseCase
from app.application.use_cases.documents.get_document_use_case import GetDocumentUseCase
from app.application.use_cases.documents.list_documents_use_case import ListDocumentsUseCase
from app.application.use_cases.documents.upload_document_use_case import UploadDocumentUseCase
from app.core.config import Settings, get_settings
from app.infrastructure.db.postgres_audit_log_repository import PostgresAuditLogRepository
from app.infrastructure.db.postgres_document_repository import PostgresDocumentRepository
from app.infrastructure.db.session import get_session
from app.infrastructure.external.hr_department_client import HrDepartmentClient
from app.infrastructure.messaging.nats_publisher import NatsPublisher
from app.infrastructure.storage.gcs_client import GCSClient
from app.infrastructure.storage.s3_client import S3StorageClient


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
logger = logging.getLogger(__name__)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session


def get_document_repository(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresDocumentRepository:
    return PostgresDocumentRepository(session)


def get_audit_logger(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresAuditLogRepository:
    return PostgresAuditLogRepository(session)


def get_storage(settings: Settings = Depends(get_settings)):
    if settings.storage_backend == "s3":
        return S3StorageClient(settings)
    return GCSClient(settings)


def get_publisher(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> NatsPublisher:
    publisher = getattr(request.app.state, "nats_publisher", None)
    if isinstance(publisher, NatsPublisher):
        return publisher
    return NatsPublisher(settings)


def get_upload_document_use_case(
    document_repository: PostgresDocumentRepository = Depends(get_document_repository),
    storage: GCSClient = Depends(get_storage),
    publisher: NatsPublisher = Depends(get_publisher),
    audit_logger: PostgresAuditLogRepository = Depends(get_audit_logger),
) -> UploadDocumentUseCase:
    return UploadDocumentUseCase(document_repository, storage, publisher, audit_logger)


def get_list_documents_use_case(
    document_repository: PostgresDocumentRepository = Depends(get_document_repository),
) -> ListDocumentsUseCase:
    return ListDocumentsUseCase(document_repository)


# Singleton (lru_cache) -> cache department dùng chung qua các request.
@lru_cache
def _hr_department_client() -> HrDepartmentClient:
    return HrDepartmentClient(get_settings().hr_service_url)


def get_hr_department_client() -> HrDepartmentClient:
    return _hr_department_client()


def get_get_document_use_case(
    document_repository: PostgresDocumentRepository = Depends(get_document_repository),
    hr_department_client: HrDepartmentClient = Depends(get_hr_department_client),
) -> GetDocumentUseCase:
    return GetDocumentUseCase(document_repository, hr_department_client)


def get_get_document_file_use_case(
    document_repository: PostgresDocumentRepository = Depends(get_document_repository),
    storage: GCSClient = Depends(get_storage),
    hr_department_client: HrDepartmentClient = Depends(get_hr_department_client),
) -> GetDocumentFileUseCase:
    return GetDocumentFileUseCase(document_repository, storage, hr_department_client)


def get_get_document_file_stream_use_case(
    document_repository: PostgresDocumentRepository = Depends(get_document_repository),
    storage: GCSClient = Depends(get_storage),
    hr_department_client: HrDepartmentClient = Depends(get_hr_department_client),
) -> GetDocumentFileStreamUseCase:
    return GetDocumentFileStreamUseCase(document_repository, storage, hr_department_client)


def get_delete_document_use_case(
    document_repository: PostgresDocumentRepository = Depends(get_document_repository),
    storage: GCSClient = Depends(get_storage),
    publisher: NatsPublisher = Depends(get_publisher),
    audit_logger: PostgresAuditLogRepository = Depends(get_audit_logger),
) -> DeleteDocumentUseCase:
    return DeleteDocumentUseCase(document_repository, storage, publisher, audit_logger)


def get_bulk_delete_documents_use_case(
    delete_use_case: DeleteDocumentUseCase = Depends(get_delete_document_use_case),
) -> BulkDeleteDocumentsUseCase:
    return BulkDeleteDocumentsUseCase(delete_use_case)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=["HS256"],
            options={"verify_exp": True},
        )
    except JWTError as exc:
        logger.info("authentication failed: invalid bearer token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        ) from exc

    user_id = payload.get("sub")
    role = payload.get("role")
    account_type = payload.get("account_type")
    if not user_id or not role or not account_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    # department KHÔNG đọc từ token: token không mang department (user-service migration 0002
    # dời department sang HR). ACL secret-doc lấy department SỐNG từ hr-service (with_live_department).
    return CurrentUser(
        id=str(user_id),
        role=str(role),
        account_type=str(account_type),
        department="",
    )


async def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PermissionDeniedError.detail,
        )
    return current_user
