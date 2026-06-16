"""add employee profile fields and fix attendance composite pk

Revision ID: 0005_add_employee_profile_fields
Revises: 0004_seed_departments
Create Date: 2026-06-16

Thêm full_name, phone_number, date_of_birth, hire_date vào hr_svc.employees.
Fix hr_svc.attendance: sole PK user_id → composite PK (user_id, period).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_add_employee_profile_fields"
down_revision: Union[str, None] = "0004_seed_departments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hr_svc.employees ADD COLUMN IF NOT EXISTS full_name VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE hr_svc.employees ADD COLUMN IF NOT EXISTS phone_number VARCHAR(30)"
    )
    op.execute(
        "ALTER TABLE hr_svc.employees ADD COLUMN IF NOT EXISTS date_of_birth DATE"
    )
    op.execute(
        "ALTER TABLE hr_svc.employees ADD COLUMN IF NOT EXISTS hire_date DATE"
    )

    # Fix attendance: sole PK user_id → composite PK (user_id, period)
    op.execute("ALTER TABLE hr_svc.attendance DROP CONSTRAINT IF EXISTS attendance_pkey")
    op.execute(
        "ALTER TABLE hr_svc.attendance ADD PRIMARY KEY (user_id, period)"
    )


def downgrade() -> None:
    op.drop_column("employees", "full_name", schema="hr_svc")
    op.drop_column("employees", "phone_number", schema="hr_svc")
    op.drop_column("employees", "date_of_birth", schema="hr_svc")
    op.drop_column("employees", "hire_date", schema="hr_svc")

    op.execute("ALTER TABLE hr_svc.attendance DROP CONSTRAINT IF EXISTS attendance_pkey")
    op.execute("ALTER TABLE hr_svc.attendance ADD PRIMARY KEY (user_id)")
