"""add account_type to employees

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004_add_account_type_to_employees'
down_revision = '0003_leave_request_write'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'employees',
        sa.Column('account_type', sa.String(length=20), server_default='internal', nullable=False),
        schema='hr_svc'
    )


def downgrade() -> None:
    op.drop_column('employees', 'account_type', schema='hr_svc')
