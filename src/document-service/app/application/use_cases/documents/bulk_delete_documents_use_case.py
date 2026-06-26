from dataclasses import dataclass, field
import logging

from app.application.auth import CurrentUser
from app.application.exceptions import NotFoundError
from app.application.use_cases.documents.common import require_admin
from app.application.use_cases.documents.delete_document_use_case import DeleteDocumentUseCase


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BulkDeleteResult:
    deleted: int
    not_found: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return f"Deleted {self.deleted} document(s)"


class BulkDeleteDocumentsUseCase:
    """Xóa nhiều tài liệu trong một request.

    Tái dùng nguyên vẹn DeleteDocumentUseCase cho từng id để mỗi doc vẫn phát 1
    event doc.access {deleted:true} riêng (query-service gỡ projection từng cái) +
    ghi audit + xóa storage best-effort. Một id lỗi KHÔNG làm hỏng cả batch.
    """

    def __init__(self, delete_document_use_case: DeleteDocumentUseCase) -> None:
        self._delete_one = delete_document_use_case

    async def execute(
        self,
        actor: CurrentUser,
        document_ids: list[str],
        ip_address: str | None = None,
    ) -> BulkDeleteResult:
        require_admin(actor)

        deleted = 0
        not_found: list[str] = []
        failed: list[str] = []
        # Khử trùng lặp, giữ thứ tự.
        seen: set[str] = set()
        for document_id in document_ids:
            if document_id in seen:
                continue
            seen.add(document_id)
            try:
                await self._delete_one.execute(
                    actor=actor,
                    document_id=document_id,
                    ip_address=ip_address,
                )
                deleted += 1
            except NotFoundError:
                not_found.append(document_id)
            except Exception:
                logger.warning("bulk delete: failed to delete document %s", document_id)
                failed.append(document_id)

        return BulkDeleteResult(deleted=deleted, not_found=not_found, failed=failed)
