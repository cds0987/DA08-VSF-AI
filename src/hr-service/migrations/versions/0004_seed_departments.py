"""seed remaining standard departments

Revision ID: 0004_seed_departments
Revises: 0003_leave_request_write
Create Date: 2026-06-15

Migration 0001 chỉ seed HR và Finance. docs/data-schema.md định nghĩa 12
phòng ban chuẩn — thêm 10 phòng còn lại. INSERT ... ON CONFLICT DO NOTHING
để idempotent (chạy lại an toàn, không đụng 2 record đã có).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_seed_departments"
down_revision: Union[str, None] = "0003_leave_request_write"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO hr_svc.departments (id, code, name)
            VALUES
                (gen_random_uuid(), 'Engineering', 'Engineering'),
                (gen_random_uuid(), 'Product',     'Product'),
                (gen_random_uuid(), 'Design',      'Design'),
                (gen_random_uuid(), 'QA',          'QA'),
                (gen_random_uuid(), 'Data',        'Data'),
                (gen_random_uuid(), 'DevOps',      'DevOps'),
                (gen_random_uuid(), 'Sales',       'Sales'),
                (gen_random_uuid(), 'Marketing',   'Marketing'),
                (gen_random_uuid(), 'Legal',       'Legal'),
                (gen_random_uuid(), 'Customer',    'Customer')
            ON CONFLICT (code) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM hr_svc.departments
            WHERE code IN (
                'Engineering', 'Product', 'Design', 'QA', 'Data',
                'DevOps', 'Sales', 'Marketing', 'Legal', 'Customer'
            )
            """
        )
    )
