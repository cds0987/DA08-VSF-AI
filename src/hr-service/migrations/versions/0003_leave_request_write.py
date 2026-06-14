"""leave request write: idempotency_key + cancelled_at

Revision ID: 0003_leave_request_write
Revises: 0002_add_benefits_performance
Create Date: 2026-06-14

Bổ sung cột cho luồng WRITE đơn nghỉ (Leave Write flow):
- idempotency_key: chống tạo trùng đơn khi client retry. UNIQUE chỉ chặn key
  non-NULL (Postgres coi NULL là distinct) -> đơn cũ/không gửi key không vỡ.
- cancelled_at: mốc thời gian hủy đơn (nhân viên tự hủy, hoặc sửa-khi-approved =
  hủy đơn cũ + tạo đơn mới). status='cancelled' đi kèm.

Additive thuần: KHÔNG đụng dữ liệu/seed/cột cũ. READ path không đổi.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_leave_request_write"
down_revision: Union[str, None] = "0002_add_benefits_performance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leave_requests",
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        schema="hr_svc",
    )
    op.add_column(
        "leave_requests",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        schema="hr_svc",
    )
    op.create_unique_constraint(
        "uq_leave_req_idempotency_key",
        "leave_requests",
        ["idempotency_key"],
        schema="hr_svc",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_leave_req_idempotency_key",
        "leave_requests",
        type_="unique",
        schema="hr_svc",
    )
    op.drop_column("leave_requests", "cancelled_at", schema="hr_svc")
    op.drop_column("leave_requests", "idempotency_key", schema="hr_svc")
