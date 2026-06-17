"""reset demo leave data cho 2 user test (logic nghỉ phép mới 4 rổ)

Revision ID: 0006_reset_demo_leave_data
Revises: 0005_add_employee_profile_fields
Create Date: 2026-06-16

Data cũ của nhanvien/sep (đơn 'personal' miễn phí + balance lệch) không khớp mô hình
4 rổ mới. Migration chạy 1 LẦN ở deploy mới: xoá sạch đơn nghỉ + reset quỹ phép của 2
user test cố định (uuid5, khớp seed_user.py). KHÔNG đụng user khác.

user_id TẤT ĐỊNH:
  nhanvien@company.com -> 0ee316e0-075f-530e-914a-884e494f3d4e
  sep@company.com      -> 2dc14f72-64f6-5361-87aa-15e859f7cf90

NOTE(build): migration này merge ở 38a7f8e nhưng các run sau fail (gate đỏ) -> image
hr-service vẫn chưa build kèm. Đụng file để build-push ở deploy này (retry sau khi e2e
hybrid-search được nới gate).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0006_reset_demo_leave_data"
down_revision: Union[str, None] = "0005_add_employee_profile_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEST_USERS = (
    "0ee316e0-075f-530e-914a-884e494f3d4e",  # nhanvien
    "2dc14f72-64f6-5361-87aa-15e859f7cf90",  # sep
)


def upgrade() -> None:
    ids = ", ".join(f"'{u}'" for u in _TEST_USERS)
    # 1) Xoá toàn bộ đơn nghỉ của 2 user test (data cũ không khớp logic mới).
    op.execute(f"DELETE FROM hr_svc.leave_requests WHERE user_id IN ({ids})")
    # 2) Reset quỹ phép về sạch + chuẩn luật (phép năm 12, ốm/BHXH 30). Upsert phòng
    #    trường hợp chưa có hồ sơ quỹ.
    for uid in _TEST_USERS:
        op.execute(
            "INSERT INTO hr_svc.leave_balance "
            "(user_id, annual_leave_total, annual_leave_used, sick_leave_total, "
            " sick_leave_used, updated_at) "
            f"VALUES ('{uid}', 12, 0, 30, 0, now()) "
            "ON CONFLICT (user_id) DO UPDATE SET "
            "  annual_leave_total = 12, annual_leave_used = 0, "
            "  sick_leave_total = 30, sick_leave_used = 0, updated_at = now()"
        )


def downgrade() -> None:
    # Không thể khôi phục data đã xoá -> no-op.
    pass
