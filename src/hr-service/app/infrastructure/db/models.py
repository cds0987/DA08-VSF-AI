from __future__ import annotations

import datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DepartmentRecord(Base):
    __tablename__ = "departments"
    __table_args__ = {"schema": "hr_svc"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmployeeRecord(Base):
    __tablename__ = "employees"
    __table_args__ = (
        Index("idx_employees_user", "user_id"),
        Index("idx_employees_department", "department"),
        Index("idx_employees_manager", "manager_user_id"),
        {"schema": "hr_svc"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    employee_code: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    company_email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    manager_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    employment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LeaveBalanceRecord(Base):
    __tablename__ = "leave_balance"
    __table_args__ = {"schema": "hr_svc"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    annual_leave_total: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    annual_leave_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sick_leave_total: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    sick_leave_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LeaveRequestRecord(Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        Index("idx_leave_req_user", "user_id"),
        Index("idx_leave_req_status", "status"),
        Index("idx_leave_req_approver", "approver_user_id", "status"),
        {"schema": "hr_svc"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    employee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("hr_svc.employees.id"), nullable=True
    )
    leave_type: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    days_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approver_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AttendanceRecord(Base):
    __tablename__ = "attendance"
    __table_args__ = {"schema": "hr_svc"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    work_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    late_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    absent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OnboardingRecord(Base):
    __tablename__ = "onboarding"
    __table_args__ = {"schema": "hr_svc"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    checklist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BenefitsRecord(Base):
    __tablename__ = "benefits"
    __table_args__ = {"schema": "hr_svc"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PerformanceReviewRecord(Base):
    __tablename__ = "performance_reviews"
    __table_args__ = (
        Index("idx_performance_user", "user_id", "period"),
        UniqueConstraint("user_id", "period", name="uq_performance_user_period"),
        {"schema": "hr_svc"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    kpi: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    reviewer_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PayrollSummaryRecord(Base):
    __tablename__ = "payroll_summary"
    __table_args__ = (
        Index("idx_payroll_user", "user_id", "period"),
        UniqueConstraint("user_id", "period", name="uq_payroll_user_period"),
        {"schema": "hr_svc"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    gross_salary: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    deductions: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    net_salary: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

