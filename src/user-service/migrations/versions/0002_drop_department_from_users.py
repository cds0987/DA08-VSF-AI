"""drop department column from user_svc.users

department đã được chuyển sang HR Service (hr_svc.employees.department).
Source of truth duy nhất cho department là HR Service, không phải user-service.

Revision ID: 0002_drop_department_from_users
Revises: 0001_baseline
Create Date: 2026-06-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_drop_department_from_users"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("users", "department", schema="user_svc")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("department", sa.String(100), nullable=False, server_default=""),
        schema="user_svc",
    )
