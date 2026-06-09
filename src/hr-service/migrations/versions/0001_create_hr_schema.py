"""create hr_svc schema and seed hr data

Revision ID: 0001_create_hr_schema
Revises:
Create Date: 2026-06-09
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_create_hr_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USER_HR = "11111111-1111-4111-8111-111111111111"
USER_FINANCE = "22222222-2222-4222-8222-222222222222"
EMP_HR = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EMP_FINANCE = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DEPT_HR = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
DEPT_FINANCE = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr_svc")

    op.create_table(
        "departments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="hr_svc",
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, unique=True),
        sa.Column("employee_code", sa.String(50), nullable=True, unique=True),
        sa.Column("company_email", sa.String(255), nullable=False, unique=True),
        sa.Column("department", sa.String(100), nullable=False),
        sa.Column("job_title", sa.String(150), nullable=True),
        sa.Column("manager_user_id", sa.String(36), nullable=True),
        sa.Column("employment_status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="hr_svc",
    )
    op.create_index("idx_employees_user", "employees", ["user_id"], schema="hr_svc")
    op.create_index("idx_employees_department", "employees", ["department"], schema="hr_svc")
    op.create_index("idx_employees_manager", "employees", ["manager_user_id"], schema="hr_svc")

    op.create_table(
        "leave_balance",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("annual_leave_total", sa.Integer, nullable=False, server_default="12"),
        sa.Column("annual_leave_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sick_leave_total", sa.Integer, nullable=False, server_default="10"),
        sa.Column("sick_leave_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="hr_svc",
    )

    op.create_table(
        "leave_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("employee_id", sa.String(36), nullable=True),
        sa.Column("leave_type", sa.String(20), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("days_count", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("approver_user_id", sa.String(36), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_svc.employees.id"]),
        schema="hr_svc",
    )
    op.create_index("idx_leave_req_user", "leave_requests", ["user_id"], schema="hr_svc")
    op.create_index("idx_leave_req_status", "leave_requests", ["status"], schema="hr_svc")
    op.create_index("idx_leave_req_approver", "leave_requests", ["approver_user_id", "status"], schema="hr_svc")

    op.create_table(
        "attendance",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("work_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("late_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("absent_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="hr_svc",
    )

    op.create_table(
        "onboarding",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),
        sa.Column("checklist", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="hr_svc",
    )

    op.create_table(
        "payroll_summary",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("gross_salary", sa.Numeric(12, 2), nullable=False),
        sa.Column("deductions", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("net_salary", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "period", name="uq_payroll_user_period"),
        schema="hr_svc",
    )
    op.create_index("idx_payroll_user", "payroll_summary", ["user_id", "period"], schema="hr_svc")

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO hr_svc.departments (id, code, name)
            VALUES
                (:dept_hr, 'HR', 'Human Resources'),
                (:dept_finance, 'FIN', 'Finance')
            """
        ),
        {"dept_hr": DEPT_HR, "dept_finance": DEPT_FINANCE},
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO hr_svc.employees
                (id, user_id, employee_code, company_email, department, job_title, manager_user_id, employment_status)
            VALUES
                (:emp_hr, :user_hr, 'E001', 'hr@example.com', 'HR', 'HR Manager', NULL, 'active'),
                (:emp_finance, :user_finance, 'E002', 'finance@example.com', 'Finance', 'Finance Analyst', :user_hr, 'active')
            """
        ),
        {
            "emp_hr": EMP_HR,
            "emp_finance": EMP_FINANCE,
            "user_hr": USER_HR,
            "user_finance": USER_FINANCE,
        },
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO hr_svc.leave_balance
                (user_id, annual_leave_total, annual_leave_used, sick_leave_total, sick_leave_used)
            VALUES
                (:user_hr, 12, 4, 10, 1),
                (:user_finance, 12, 7, 10, 0)
            """
        ),
        {"user_hr": USER_HR, "user_finance": USER_FINANCE},
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO hr_svc.leave_requests
                (id, user_id, employee_id, leave_type, start_date, end_date, days_count, status, reason, approver_user_id)
            VALUES
                ('leave-hr-001', :user_hr, :emp_hr, 'annual', '2026-06-10', '2026-06-11', 2, 'approved', NULL, :user_hr),
                ('leave-hr-002', :user_hr, :emp_hr, 'sick', '2026-06-18', '2026-06-18', 1, 'pending', NULL, :user_hr),
                ('leave-fin-001', :user_finance, :emp_finance, 'annual', '2026-06-18', '2026-06-18', 1, 'pending', NULL, :user_hr)
            """
        ),
        {
            "user_hr": USER_HR,
            "user_finance": USER_FINANCE,
            "emp_hr": EMP_HR,
            "emp_finance": EMP_FINANCE,
        },
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO hr_svc.attendance (user_id, period, work_days, late_count, absent_count)
            VALUES
                (:user_hr, '2026-06', 20, 1, 0),
                (:user_finance, '2026-06', 19, 2, 1)
            """
        ),
        {"user_hr": USER_HR, "user_finance": USER_FINANCE},
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO hr_svc.onboarding (user_id, status, checklist)
            VALUES
                (:user_hr, 'completed', :cl1),
                (:user_finance, 'in_progress', :cl2)
            """
        ),
        {
            "user_hr": USER_HR,
            "user_finance": USER_FINANCE,
            "cl1": '[{"task":"Nhat laptop va the","done":true},{"task":"Hoan thanh dao tao bao mat","done":true},{"task":"Gap go team","done":true}]',
            "cl2": '[{"task":"Nhat laptop va the","done":true},{"task":"Hoan thanh dao tao bao mat","done":false},{"task":"Gap go team","done":false}]',
        },
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO hr_svc.payroll_summary
                (id, user_id, period, gross_salary, deductions, net_salary)
            VALUES
                ('pay-hr-001', :user_hr, '2026-05', 1200.00, 200.00, 1000.00),
                ('pay-fin-001', :user_finance, '2026-05', 1500.00, 250.00, 1250.00)
            """
        ),
        {"user_hr": USER_HR, "user_finance": USER_FINANCE},
    )


def downgrade() -> None:
    op.drop_index("idx_payroll_user", table_name="payroll_summary", schema="hr_svc")
    op.drop_table("payroll_summary", schema="hr_svc")
    op.drop_table("onboarding", schema="hr_svc")
    op.drop_table("attendance", schema="hr_svc")
    op.drop_index("idx_leave_req_approver", table_name="leave_requests", schema="hr_svc")
    op.drop_index("idx_leave_req_status", table_name="leave_requests", schema="hr_svc")
    op.drop_index("idx_leave_req_user", table_name="leave_requests", schema="hr_svc")
    op.drop_table("leave_requests", schema="hr_svc")
    op.drop_table("leave_balance", schema="hr_svc")
    op.drop_index("idx_employees_manager", table_name="employees", schema="hr_svc")
    op.drop_index("idx_employees_department", table_name="employees", schema="hr_svc")
    op.drop_index("idx_employees_user", table_name="employees", schema="hr_svc")
    op.drop_table("employees", schema="hr_svc")
    op.drop_table("departments", schema="hr_svc")
    op.execute("DROP SCHEMA IF EXISTS hr_svc CASCADE")
