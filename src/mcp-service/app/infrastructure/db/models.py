"""SQLAlchemy ORM models cho schema hr_mock (mcp_db).

Source of truth DDL: docs/data-schema.md → HR Mock Data section.
Migration: src/mcp-service/migrations/versions/0001_create_hr_schema.py
"""
from __future__ import annotations

import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, Date
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LeaveBalanceRecord(Base):
    __tablename__ = "leave_balance"
    __table_args__ = {"schema": "hr_mock"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    annual_leave_total: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    annual_leave_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sick_leave_total: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    sick_leave_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class LeaveRequestRecord(Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        Index("idx_leave_req_user", "user_id"),
        {"schema": "hr_mock"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    leave_type: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    days_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AttendanceRecord(Base):
    __tablename__ = "attendance"
    __table_args__ = {"schema": "hr_mock"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    work_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    late_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    absent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class OnboardingRecord(Base):
    __tablename__ = "onboarding"
    __table_args__ = {"schema": "hr_mock"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    checklist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class PayrollSummaryRecord(Base):
    __tablename__ = "payroll_summary"
    __table_args__ = (
        Index("idx_payroll_user", "user_id", "period"),
        {"schema": "hr_mock"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    gross_salary: Mapped[float] = mapped_column(nullable=False)
    deductions: Mapped[float] = mapped_column(nullable=False, default=0)
    net_salary: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
