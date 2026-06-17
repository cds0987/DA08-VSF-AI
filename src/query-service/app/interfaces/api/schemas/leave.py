"""Pydantic schemas cho Leave WRITE REST (frontend <-> query-service).

user_id KHÔNG có trong request — luôn lấy từ JWT server-side (chống user A thao tác
hộ user B). approver_user_id (duyệt) = chính người đang đăng nhập.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LeaveCreateRequest(BaseModel):
    # 4 rổ luật LĐ VN (khớp hr-service registry). 'personal' giữ cho tương thích đơn cũ.
    leave_type: Literal[
        "annual", "marriage", "child_marriage", "bereavement", "sick", "maternity", "unpaid", "personal",
    ]
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    reason: str = ""
    # Chống tạo trùng khi double-click/retry: frontend sinh 1 key/lần mở form.
    idempotency_key: Optional[str] = None
    # User đã xem cảnh báo chồng ngày và vẫn muốn tạo -> bỏ qua cảnh báo overlap.
    confirm_overlap: bool = False


class LeaveCancelRequest(BaseModel):
    # rỗng — request_id ở path, user_id từ JWT.
    pass


class LeaveDecisionRequest(BaseModel):
    reason: str = ""  # dùng khi reject
