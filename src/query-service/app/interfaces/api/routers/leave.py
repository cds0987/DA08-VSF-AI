"""Leave WRITE REST endpoints (public qua nginx /api/query/leave-requests*).

KIẾN TRÚC AN TOÀN: frontend gọi query-service bằng JWT -> query-service lấy user_id
TỪ TOKEN (không tin client) -> gọi hr-service bằng X-Internal-Token. hr-service chỉ
nhận internal token, KHÔNG xác thực user -> nên KHÔNG được expose thẳng ra browser.

- Nhân viên: tạo / hủy đơn của CHÍNH MÌNH (user_id = JWT).
- Người duyệt: xem hàng đợi + duyệt/từ chối đơn mà MÌNH là approver (approver_user_id
  = JWT). hr-service tự guard approver == đơn.approver_user_id.

Lỗi nghiệp vụ từ hr-service (403/404/409/422) được map nguyên trạng cho frontend.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.application.ports import AuthenticatedUser
from app.infrastructure.external.hr_leave_client import HRLeaveClient
from app.interfaces.api.dependencies import get_current_user, get_hr_leave_client
from app.interfaces.api.schemas.leave import (
    LeaveCancelRequest,
    LeaveCreateRequest,
    LeaveDecisionRequest,
)

logger = logging.getLogger("query-service")

router = APIRouter(prefix="/leave-requests", tags=["leave"])


def _raise_for_status(status_code: int, body: dict) -> None:
    if 200 <= status_code < 300:
        return
    detail = body.get("detail") if isinstance(body, dict) else None
    raise HTTPException(status_code=status_code, detail=detail or "leave service error")


@router.post("", status_code=201)
async def create_leave_request(
    payload: LeaveCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    hr: HRLeaveClient = Depends(get_hr_leave_client),
) -> dict:
    """Nhân viên tạo đơn nghỉ. user_id = JWT (không tin client)."""
    status_code, body = await hr.create(
        user_id=user.id,
        leave_type=payload.leave_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=payload.reason,
        idempotency_key=payload.idempotency_key or str(uuid.uuid4()),
        confirm_overlap=payload.confirm_overlap,
    )
    _raise_for_status(status_code, body)
    return body


@router.post("/{request_id}/cancel")
async def cancel_leave_request(
    request_id: str,
    _payload: LeaveCancelRequest | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
    hr: HRLeaveClient = Depends(get_hr_leave_client),
) -> dict:
    """Nhân viên hủy đơn của chính mình (hr-service guard chủ đơn theo user_id)."""
    status_code, body = await hr.cancel(user_id=user.id, request_id=request_id)
    _raise_for_status(status_code, body)
    return body


@router.get("/pending-approval")
async def pending_approval(
    user: AuthenticatedUser = Depends(get_current_user),
    hr: HRLeaveClient = Depends(get_hr_leave_client),
) -> dict:
    """Hàng đợi đơn chờ DUYỆT của người đang đăng nhập (approver_user_id = JWT)."""
    status_code, body = await hr.list_pending_approval(approver_user_id=user.id)
    _raise_for_status(status_code, body)
    return body


@router.post("/{request_id}/approve")
async def approve_leave_request(
    request_id: str,
    _payload: LeaveDecisionRequest | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
    hr: HRLeaveClient = Depends(get_hr_leave_client),
) -> dict:
    status_code, body = await hr.decide(
        request_id=request_id, approver_user_id=user.id, action="approve"
    )
    _raise_for_status(status_code, body)
    return body


@router.post("/{request_id}/reject")
async def reject_leave_request(
    request_id: str,
    payload: LeaveDecisionRequest | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
    hr: HRLeaveClient = Depends(get_hr_leave_client),
) -> dict:
    reason = payload.reason if payload else ""
    status_code, body = await hr.decide(
        request_id=request_id, approver_user_id=user.id, action="reject", reason=reason
    )
    _raise_for_status(status_code, body)
    return body


# Đặt SAU /pending-approval để không nuốt route tĩnh đó vào {request_id}.
@router.get("/{request_id}")
async def get_leave_request(
    request_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    hr: HRLeaveClient = Depends(get_hr_leave_client),
) -> dict:
    """Trạng thái đơn của chính chủ đơn (user_id = JWT). Card chat dùng để hiện trạng
    thái duyệt sống."""
    status_code, body = await hr.get(user_id=user.id, request_id=request_id)
    _raise_for_status(status_code, body)
    return body
