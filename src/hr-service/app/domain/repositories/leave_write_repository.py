"""Interface WRITE cho đơn nghỉ phép — TÁCH HẲN khỏi HrRepository (read).

Lý do tách (Bẫy 1 trong leave-request-write-implementation.md): `FakeHrRepository`
trong test read implement đủ method abstract của `HrRepository`. Nếu thêm abstract
method write vào `HrRepository` -> fake thành abstract -> rớt toàn bộ test read.
Nên write có interface riêng; `PostgresHrRepository` kế thừa CẢ HAI, test write dùng
fake riêng (`FakeLeaveWriteRepository`).

Mọi method async, trả `dict` (JSON-friendly cho endpoint). Lỗi nghiệp vụ raise các
exception dưới -> routes map sang HTTP code tương ứng.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal, Optional


class LeaveWriteError(Exception):
    """Gốc cho mọi lỗi nghiệp vụ write (để routes bắt chung nếu cần)."""


class ApproverNotConfigured(LeaveWriteError):
    """Nhân viên không có manager và HR_DEFAULT_APPROVER rỗng -> 422."""


class LeaveRequestNotFound(LeaveWriteError):
    """Không tìm thấy đơn theo id -> 404."""


class LeaveRequestForbidden(LeaveWriteError):
    """Người gọi không phải chủ đơn (sửa/hủy) hoặc không phải approver (duyệt) -> 403."""


class LeaveRequestConflict(LeaveWriteError):
    """Đơn không ở trạng thái hợp lệ cho thao tác (vd duyệt đơn đã duyệt) -> 409."""


class InsufficientLeaveBalance(LeaveWriteError):
    """Duyệt mà số ngày vượt hạn mức còn lại -> 409 (rollback, đơn giữ pending)."""


class LeaveRequestDuplicate(LeaveWriteError):
    """Đã có đơn active (pending/approved) TRÙNG TOÀN BỘ (cùng loại + cùng khoảng
    ngày + cùng lý do) -> 409. Chống tạo lặp khi mỗi lượt chat sinh idempotency_key
    mới (idempotency_key chỉ chặn double-submit cùng 1 form). KHÁC lý do/loại hoặc
    chỉ đè 1 phần ngày -> KHÔNG coi là trùng, vẫn cho tạo. Mang theo đơn trùng để báo.
    """

    def __init__(self, message: str, *, existing: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.existing = existing or {}


class LeaveRequestOverlapWarning(LeaveWriteError):
    """Có đơn active CHỒNG NGÀY nhưng KHÁC nội dung (không phải trùng toàn bộ) -> 409
    CẢNH BÁO (không chặn cứng). User có thể quên đã đặt đơn ngày đó -> FE hiện form
    riêng + chi tiết đơn cũ; muốn vẫn tạo thì gọi lại với confirm_overlap=True.
    """

    def __init__(self, message: str, *, existing: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.existing = existing or []


class LeaveWriteRepository(ABC):
    @abstractmethod
    async def create_leave_request(
        self,
        *,
        user_id: str,
        leave_type: str,
        start_date: str,
        end_date: str,
        reason: str,
        default_approver: str,
        idempotency_key: Optional[str] = None,
        confirm_overlap: bool = False,
    ) -> dict[str, Any]:
        """Tạo đơn pending. Resolve approver = manager_user_id OR default_approver
        (rỗng -> ApproverNotConfigured). days_count server tính (ngày lịch).
        idempotency_key trùng -> trả đơn cũ (created=False), KHÔNG tạo thêm.
        Trùng TOÀN BỘ (loại+ngày+lý do, đơn active) -> LeaveRequestDuplicate (chặn).
        Chồng ngày nhưng khác nội dung & confirm_overlap=False -> LeaveRequestOverlapWarning.
        confirm_overlap=True -> bỏ qua cảnh báo chồng ngày, vẫn tạo.
        Trả: {"request": <đơn>, "created": bool}."""
        raise NotImplementedError

    @abstractmethod
    async def update_leave_request(
        self,
        *,
        user_id: str,
        request_id: str,
        leave_type: str,
        start_date: str,
        end_date: str,
        reason: str,
        default_approver: str,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Sửa đơn (chỉ chủ đơn). pending -> sửa tại chỗ (mode='updated'). approved ->
        hủy đơn cũ + HOÀN phép + tạo đơn pending MỚI (mode='replaced'). rejected/
        cancelled -> LeaveRequestConflict.
        Trả: {"request": <đơn kết quả>, "mode": "updated"|"replaced",
              "replaced_request": <đơn cũ đã hủy>|None}."""
        raise NotImplementedError

    @abstractmethod
    async def cancel_leave_request(
        self, *, user_id: str, request_id: str
    ) -> dict[str, Any]:
        """Hủy đơn (chỉ chủ đơn). approved -> HOÀN phép. pending -> hủy thẳng.
        rejected/cancelled -> no-op idempotent (changed=False).
        Trả: {"request": <đơn>, "changed": bool}."""
        raise NotImplementedError

    @abstractmethod
    async def list_pending_approval(
        self, approver_user_id: str
    ) -> list[dict[str, Any]]:
        """Danh sách đơn status='pending' mà approver_user_id là người duyệt."""
        raise NotImplementedError

    async def get_leave_request(
        self, *, user_id: str, request_id: str
    ) -> Optional[dict[str, Any]]:
        """Trả 1 đơn của CHÍNH chủ đơn (scope user_id) hoặc None nếu không có/không thuộc
        user. Không abstract -> fake/test cũ không bắt buộc implement."""
        raise NotImplementedError

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Danh sách MỌI đơn của chính chủ đơn (mọi trạng thái), mới nhất trước -> để
        nhân viên xem lại đơn mình gửi + trạng thái duyệt. Không abstract -> fake cũ
        không bắt buộc implement."""
        raise NotImplementedError

    @abstractmethod
    async def update_leave_status(
        self,
        *,
        request_id: str,
        approver_user_id: str,
        action: Literal["approve", "reject"],
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Duyệt/từ chối (chỉ người duyệt của đơn, đơn phải pending). approve -> trừ
        balance trong transaction (thiếu -> InsufficientLeaveBalance). reject -> set
        rejected_reason. Sai approver -> Forbidden; không pending -> Conflict.
        Trả: {"request": <đơn>}."""
        raise NotImplementedError
