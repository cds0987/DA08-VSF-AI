from dataclasses import dataclass
from typing import Any, Protocol

from app.application.auth import CurrentUser
from app.application.exceptions import NotFoundError, PermissionDeniedError, StorageError
from app.application.use_cases.documents.common import (
    ALLOWED_EXTENSIONS,
    can_access_document,
    with_live_department,
)
from app.domain.repositories.document_repository import DocumentRepository


class StreamStorage(Protocol):
    async def download_file(self, key: str) -> bytes:
        ...


# Content-Type cho từng đuôi file. Đẩy bytes qua domain mình (proxy) thay vì presigned-URL
# GCS, nên PHẢI tự set Content-Type đúng để trình duyệt render inline thay vì tải nhầm.
_MEDIA_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# Loại trình duyệt render được native -> mở inline (ngay trên vsfchat). Office/nhị phân khác
# trình duyệt không render được -> attachment (tải về trong domain mình, KHÔNG bay sang
# officeapps/google), tránh rò tài liệu mật sang bên thứ ba.
_INLINE_TYPES = {"pdf", "txt", "md", "csv", "png", "jpg", "jpeg", "gif", "webp"}


@dataclass(frozen=True)
class DocumentFileStreamResult:
    content: bytes
    media_type: str
    filename: str
    disposition: str


class GetDocumentFileStreamUseCase:
    def __init__(
        self,
        document_repository: DocumentRepository,
        storage: StreamStorage,
        hr_department_client: Any | None = None,
    ) -> None:
        self.document_repository = document_repository
        self.storage = storage
        self.hr_department_client = hr_department_client

    async def execute(self, user: CurrentUser, document_id: str) -> DocumentFileStreamResult:
        document = await self.document_repository.get_by_id(document_id)
        if document is None:
            raise NotFoundError()
        # department lấy SỐNG từ HR cho secret-doc (KHÔNG từ token) — đồng nhất ACL với
        # GetDocumentFileUseCase.
        user = await with_live_department(user, document.classification, self.hr_department_client)
        if not can_access_document(
            user,
            document.classification,
            document.allowed_departments,
            document.allowed_user_ids,
        ):
            raise PermissionDeniedError("Khong co quyen xem tai lieu nay")

        file_type = _normalize_file_type(document.file_type)
        try:
            content = await self.storage.download_file(document.gcs_key)
        except Exception as exc:
            raise StorageError() from exc

        return DocumentFileStreamResult(
            content=content,
            media_type=_MEDIA_TYPES[file_type],
            filename=document.name,
            disposition="inline" if file_type in _INLINE_TYPES else "attachment",
        )


def _normalize_file_type(file_type: str) -> str:
    normalized = file_type.strip().lower().lstrip(".")
    if normalized not in ALLOWED_EXTENSIONS or normalized not in _MEDIA_TYPES:
        raise StorageError("Unsupported document file type")
    return normalized
