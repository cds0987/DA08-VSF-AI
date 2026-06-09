"""PostgreSQL implementation của HrRepository.

Dùng sync SQLAlchemy + asyncio.to_thread để tránh block event loop của uvicorn.
Mọi method bắt buộc filter WHERE user_id — không có đường query data người khác.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.domain.entities.tool_io import (
    AttendanceDTO,
    LeaveBalanceDTO,
    LeaveRequestDTO,
    OnboardingDTO,
    OnboardingItemDTO,
    PayrollDTO,
)
from app.domain.repositories.hr_repository import HrRepository
from app.infrastructure.db.models import (
    AttendanceRecord,
    LeaveBalanceRecord,
    LeaveRequestRecord,
    OnboardingRecord,
    PayrollSummaryRecord,
)


class PostgresHrRepository(HrRepository):
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        # Engine tạo lazy — cho phép tool được instantiate khi URL chưa set;
        # verify() sẽ fail-closed nếu URL rỗng hoặc DB không reach được.
        self._engine = None
        self._session_factory: sessionmaker[Session] | None = None

    def _ensure_engine(self) -> None:
        if self._engine is not None:
            return
        if not self._database_url:
            raise RuntimeError(
                "hr_query: MCP_DATABASE_URL chưa được cấu hình. "
                "Set TOOL_HR_QUERY_ENABLED=1 và MCP_DATABASE_URL."
            )
        self._engine = create_engine(self._database_url, pool_pre_ping=True)
        self._session_factory = sessionmaker(
            bind=self._engine, autoflush=False, autocommit=False
        )

    # ── internal ─────────────────────────────────────────────────────────────

    def _session(self) -> Session:
        self._ensure_engine()
        return self._session_factory()  # type: ignore[misc]

    # ── HrRepository ─────────────────────────────────────────────────────────

    async def ping(self) -> None:
        def _ping() -> None:
            self._ensure_engine()
            with self._session() as s:
                s.execute(sa.text("SELECT 1"))

        await asyncio.to_thread(_ping)

    async def get_leave_balance(self, user_id: str) -> Optional[LeaveBalanceDTO]:
        def _query() -> Optional[LeaveBalanceDTO]:
            with self._session() as s:
                row = s.get(LeaveBalanceRecord, user_id)
                if row is None:
                    return None
                return LeaveBalanceDTO(
                    annual_total=row.annual_leave_total,
                    annual_used=row.annual_leave_used,
                    annual_remaining=row.annual_leave_total - row.annual_leave_used,
                    sick_total=row.sick_leave_total,
                    sick_used=row.sick_leave_used,
                    sick_remaining=row.sick_leave_total - row.sick_leave_used,
                )

        return await asyncio.to_thread(_query)

    async def get_leave_requests(self, user_id: str) -> List[LeaveRequestDTO]:
        def _query() -> List[LeaveRequestDTO]:
            with self._session() as s:
                rows = (
                    s.query(LeaveRequestRecord)
                    .filter(LeaveRequestRecord.user_id == user_id)
                    .order_by(LeaveRequestRecord.created_at.desc())
                    .all()
                )
                return [
                    LeaveRequestDTO(
                        leave_type=row.leave_type,
                        start_date=str(row.start_date),
                        end_date=str(row.end_date),
                        days_count=row.days_count,
                        status=row.status,
                    )
                    for row in rows
                ]

        return await asyncio.to_thread(_query)

    async def get_attendance(self, user_id: str) -> Optional[AttendanceDTO]:
        def _query() -> Optional[AttendanceDTO]:
            with self._session() as s:
                row = s.get(AttendanceRecord, user_id)
                if row is None:
                    return None
                return AttendanceDTO(
                    period=row.period,
                    work_days=row.work_days,
                    late_count=row.late_count,
                    absent_count=row.absent_count,
                )

        return await asyncio.to_thread(_query)

    async def get_onboarding(self, user_id: str) -> Optional[OnboardingDTO]:
        def _query() -> Optional[OnboardingDTO]:
            with self._session() as s:
                row = s.get(OnboardingRecord, user_id)
                if row is None:
                    return None
                checklist = [
                    OnboardingItemDTO(task=item["task"], done=bool(item.get("done")))
                    for item in (row.checklist or [])
                    if isinstance(item, dict)
                ]
                completed = sum(1 for item in checklist if item.done)
                return OnboardingDTO(
                    status=row.status,
                    checklist=checklist,
                    completed_count=completed,
                    total_count=len(checklist),
                )

        return await asyncio.to_thread(_query)

    async def get_payroll(self, user_id: str) -> List[PayrollDTO]:
        def _query() -> List[PayrollDTO]:
            with self._session() as s:
                rows = (
                    s.query(PayrollSummaryRecord)
                    .filter(PayrollSummaryRecord.user_id == user_id)
                    .order_by(PayrollSummaryRecord.period.desc())
                    .all()
                )
                return [
                    PayrollDTO(
                        period=row.period,
                        gross_salary=float(row.gross_salary),
                        deductions=float(row.deductions),
                        net_salary=float(row.net_salary),
                    )
                    for row in rows
                ]

        return await asyncio.to_thread(_query)

    async def aclose(self) -> None:
        def _dispose() -> None:
            if self._engine is not None:
                self._engine.dispose()

        await asyncio.to_thread(_dispose)
