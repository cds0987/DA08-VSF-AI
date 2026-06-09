"""create hr_mock schema and seed MVP tables

Revision ID: 0001_create_hr_schema
Revises:
Create Date: 2026-06-09

Tạo schema hr_mock trong mcp_db + 4 bảng MVP:
  leave_balance, leave_requests, attendance, onboarding
Seed 2 user mẫu (UUIDs khớp với test fixtures).
payroll_summary tạo sẵn nhưng chưa expose tool (chờ SA-3 chốt role-gate).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_create_hr_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# UUID seed — khớp với test fixtures trong tests/test_hr_query_tool.py
_USER_HR = "11111111-1111-4111-8111-111111111111"
_USER_FINANCE = "22222222-2222-4222-8222-222222222222"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr_mock")

    # ── leave_balance ─────────────────────────────────────────────────────────
    op.create_table(
        "leave_balance",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("annual_leave_total", sa.Integer, nullable=False, server_default="12"),
        sa.Column("annual_leave_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sick_leave_total", sa.Integer, nullable=False, server_default="10"),
        sa.Column("sick_leave_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        schema="hr_mock",
    )

    # ── leave_requests ────────────────────────────────────────────────────────
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("leave_type", sa.String(20), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("days_count", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        schema="hr_mock",
    )
    op.create_index("idx_leave_req_user", "leave_requests", ["user_id"], schema="hr_mock")

    # ── attendance ────────────────────────────────────────────────────────────
    op.create_table(
        "attendance",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("work_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("late_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("absent_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        schema="hr_mock",
    )

    # ── onboarding ────────────────────────────────────────────────────────────
    op.create_table(
        "onboarding",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="'in_progress'"),
        sa.Column("checklist", JSONB, nullable=False, server_default="'[]'"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        schema="hr_mock",
    )

    # ── payroll_summary (schema sẵn, chưa expose tool) ───────────────────────
    op.create_table(
        "payroll_summary",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("gross_salary", sa.Numeric(12, 2), nullable=False),
        sa.Column("deductions", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("net_salary", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "period", name="uq_payroll_user_period"),
        schema="hr_mock",
    )
    op.create_index("idx_payroll_user", "payroll_summary", ["user_id", "period"],
                    schema="hr_mock")

    # ── seed data ─────────────────────────────────────────────────────────────
    conn = op.get_bind()

    conn.execute(sa.text("""
        INSERT INTO hr_mock.leave_balance
            (user_id, annual_leave_total, annual_leave_used, sick_leave_total, sick_leave_used)
        VALUES
            (:u1, 12, 4, 10, 1),
            (:u2, 12, 7, 10, 0)
    """), {"u1": _USER_HR, "u2": _USER_FINANCE})

    conn.execute(sa.text("""
        INSERT INTO hr_mock.leave_requests
            (id, user_id, leave_type, start_date, end_date, days_count, status)
        VALUES
            ('leave-hr-001',  :u1, 'annual', '2026-06-10', '2026-06-11', 2, 'approved'),
            ('leave-hr-002',  :u1, 'sick',   '2026-06-18', '2026-06-18', 1, 'pending'),
            ('leave-fin-001', :u2, 'annual', '2026-06-18', '2026-06-18', 1, 'pending')
    """), {"u1": _USER_HR, "u2": _USER_FINANCE})

    conn.execute(sa.text("""
        INSERT INTO hr_mock.attendance (user_id, period, work_days, late_count, absent_count)
        VALUES
            (:u1, '2026-06', 20, 1, 0),
            (:u2, '2026-06', 19, 2, 1)
    """), {"u1": _USER_HR, "u2": _USER_FINANCE})

    conn.execute(sa.text("""
        INSERT INTO hr_mock.onboarding (user_id, status, checklist)
        VALUES
            (:u1, 'completed', :cl1),
            (:u2, 'in_progress', :cl2)
    """), {
        "u1": _USER_HR,
        "cl1": '[{"task":"Nhận laptop và thẻ","done":true},{"task":"Hoàn thành đào tạo bảo mật","done":true},{"task":"Gặp gỡ team","done":true}]',
        "u2": _USER_FINANCE,
        "cl2": '[{"task":"Nhận laptop và thẻ","done":true},{"task":"Hoàn thành đào tạo bảo mật","done":false},{"task":"Gặp gỡ team","done":false}]',
    })


def downgrade() -> None:
    op.drop_index("idx_payroll_user", table_name="payroll_summary", schema="hr_mock")
    op.drop_table("payroll_summary", schema="hr_mock")
    op.drop_table("onboarding", schema="hr_mock")
    op.drop_table("attendance", schema="hr_mock")
    op.drop_index("idx_leave_req_user", table_name="leave_requests", schema="hr_mock")
    op.drop_table("leave_requests", schema="hr_mock")
    op.drop_table("leave_balance", schema="hr_mock")
    op.execute("DROP SCHEMA IF EXISTS hr_mock CASCADE")
