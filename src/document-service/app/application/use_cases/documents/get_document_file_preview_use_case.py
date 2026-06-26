import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.application.auth import CurrentUser
from app.application.exceptions import NotFoundError, PermissionDeniedError, StorageError
from app.application.ports.document_converter import DocumentConverter
from app.application.use_cases.documents.common import (
    can_access_document,
    with_live_department,
)
# Tái dùng bảng media-type + tập native-inline + chuẩn hoá đuôi từ stream use case (DRY).
from app.application.use_cases.documents.get_document_file_stream_use_case import (
    _INLINE_TYPES as NATIVE_INLINE_TYPES,
    _MEDIA_TYPES,
    _normalize_file_type,
)
from app.domain.repositories.document_repository import DocumentRepository

logger = logging.getLogger(__name__)

_PDF_MEDIA_TYPE = "application/pdf"


class PreviewStorage(Protocol):
    async def download_file(self, key: str) -> bytes: ...
    async def upload_file(self, key: str, content: bytes, content_type: str | None = None) -> None: ...
    async def file_exists(self, key: str) -> bool: ...


@dataclass(frozen=True)
class DocumentFilePreviewResult:
    content: bytes
    media_type: str
    filename: str


def _is_valid_pdf(data: bytes) -> bool:
    return len(data) > 0 and data[:5] == b"%PDF-"


class GetDocumentFilePreviewUseCase:
    def __init__(
        self,
        document_repository: DocumentRepository,
        storage: PreviewStorage,
        converter: DocumentConverter,
        hr_department_client: Any | None = None,
    ) -> None:
        self.document_repository = document_repository
        self.storage = storage
        self.converter = converter
        self.hr_department_client = hr_department_client

    async def execute(self, user: CurrentUser, document_id: str) -> DocumentFilePreviewResult:
        document = await self.document_repository.get_by_id(document_id)
        if document is None:
            raise NotFoundError()
        user = await with_live_department(user, document.classification, self.hr_department_client)
        if not can_access_document(
            user,
            document.classification,
            document.allowed_departments,
            document.allowed_user_ids,
        ):
            raise PermissionDeniedError("Khong co quyen xem tai lieu nay")

        file_type = _normalize_file_type(document.file_type)

        # Native: trình duyệt render được -> passthrough nguyên bản, KHÔNG cache.
        if file_type in NATIVE_INLINE_TYPES:
            try:
                content = await self.storage.download_file(document.gcs_key)
            except Exception as exc:
                raise StorageError("Failed to fetch document for preview") from exc
            return DocumentFilePreviewResult(content, _MEDIA_TYPES[file_type], document.name)

        # Office: cache -> convert.
        preview_key = f"previews/{document_id}.pdf"
        cached = await self._read_cache(preview_key, document_id, file_type)
        if cached is not None:
            return DocumentFilePreviewResult(cached, _PDF_MEDIA_TYPE, document.name)

        pdf = await self._convert(document, file_type)
        await self._write_cache(preview_key, pdf, document_id)
        return DocumentFilePreviewResult(pdf, _PDF_MEDIA_TYPE, document.name)

    async def _read_cache(self, preview_key: str, document_id: str, file_type: str) -> bytes | None:
        try:
            if not await self.storage.file_exists(preview_key):
                logger.info("preview cache=miss document_id=%s file_type=%s", document_id, file_type)
                return None
            data = await self.storage.download_file(preview_key)
        except Exception:
            logger.warning("preview cache read failed document_id=%s -> reconvert", document_id)
            return None
        if not _is_valid_pdf(data):
            logger.warning("preview cache=corrupt document_id=%s -> reconvert", document_id)
            return None
        logger.info("preview cache=hit document_id=%s", document_id)
        return data

    async def _convert(self, document: Any, file_type: str) -> bytes:
        started = time.monotonic()
        try:
            original = await self.storage.download_file(document.gcs_key)
        except Exception as exc:
            logger.warning(
                "preview download failed document_id=%s file_type=%s reason=%s",
                document.id, file_type, type(exc).__name__,
            )
            raise StorageError("Failed to fetch document for preview") from exc
        try:
            pdf = await self.converter.convert_to_pdf(original, document.name)
        except Exception as exc:
            logger.warning(
                "preview convert failed document_id=%s file_type=%s reason=%s",
                document.id, file_type, type(exc).__name__,
            )
            raise StorageError("Document preview conversion failed") from exc
        if not _is_valid_pdf(pdf):
            logger.warning("preview convert produced non-PDF document_id=%s", document.id)
            raise StorageError("Document preview conversion failed")
        logger.info(
            "preview cache=miss->converted document_id=%s file_type=%s latency_ms=%s",
            document.id, file_type, int((time.monotonic() - started) * 1000),
        )
        return pdf

    async def _write_cache(self, preview_key: str, pdf: bytes, document_id: str) -> None:
        try:
            await self.storage.upload_file(preview_key, pdf, _PDF_MEDIA_TYPE)
        except Exception:
            # Ghi cache lỗi KHÔNG làm hỏng request — vẫn trả PDF đã convert.
            logger.warning("preview cache write failed document_id=%s (served anyway)", document_id)
