from __future__ import annotations

import asyncio
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.domain.entities.dtos import (
    AttendanceDTO,
    BenefitItemDTO,
    BenefitsDTO,
    LeaveBalanceDTO,
    LeaveRequestDTO,
    OnboardingDTO,
    OnboardingItemDTO,
    PayrollDTO,
    PerformanceReviewDTO,
)
from app.domain.repositories.hr_repository import HrRepository
from app.infrastructure.db.models import (
    AttendanceRecord,
    BenefitsRecord,
    LeaveBalanceRecord,
    LeaveRequestRecord,
    OnboardingRecord,
    PayrollSummaryRecord,
    PerformanceReviewRecord,
)


class PostgresHrRepository(HrRepository):
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._engine = None
        self._session_factory: sessionmaker[Session] | None = None

    def _ensure_engine(self) -> None:
        if self._engine is not None:
            return
        if not self._database_url:
            raise RuntimeError("hr-service: database_url is not configured")
        self._engine = create_engine(self._database_url, pool_pre_ping=True)
        self._session_factory = sessionmaker(bind=self._engine, autoflush=False, autocommit=False)

    def _session(self) -> Session:
        self._ensure_engine()
        return self._session_factory()  # type: ignore[misc]

    async def ping(self) -> None:
        def _ping() -> None:
            self._ensure_engine()
            with self._session() as session:
                session.execute(sa.text("SELECT 1"))

        await asyncio.to_thread(_ping)

    async def get_leave_balance(self, user_id: str) -> Optional[LeaveBalanceDTO]:
        def _query() -> Optional[LeaveBalanceDTO]:
            with self._session() as session:
                row = session.get(LeaveBalanceRecord, user_id)
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

    async def ensure_leave_balance(self, user_id: str) -> None:
        def _ensure() -> None:
            with self._session() as session:
                # Chỉ chèn user_id; các cột còn lại lấy server_default migration (12/10/0/now).
                # ON CONFLICT DO NOTHING -> idempotent, an toàn khi gọi đua.
                session.execute(
                    sa.text(
                        "INSERT INTO hr_svc.leave_balance (user_id) VALUES (:uid) "
                        "ON CONFLICT (user_id) DO NOTHING"
                    ),
                    {"uid": user_id},
                )
                session.commit()

        await asyncio.to_thread(_ensure)

    async def upsert_employee_from_user(
        self, user_id: str, email: str, department: str, is_active: bool
    ) -> None:
        import uuid

        status = "active" if is_active else "inactive"

        def _upsert() -> None:
            with self._session() as session:
                # Upsert theo user_id (unique). created_at/updated_at lấy server_default.
                session.execute(
                    sa.text(
                        "INSERT INTO hr_svc.employees "
                        "(id, user_id, company_email, department, employment_status) "
                        "VALUES (:id, :uid, :email, :dept, :status) "
                        "ON CONFLICT (user_id) DO UPDATE SET "
                        "  company_email = EXCLUDED.company_email, "
                        "  department = EXCLUDED.department, "
                        "  employment_status = EXCLUDED.employment_status, "
                        "  updated_at = now()"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "uid": user_id,
                        "email": email or f"{user_id}@unknown.local",
                        "dept": department or "",
                        "status": status,
                    },
                )
                session.commit()

        await asyncio.to_thread(_upsert)

    async def get_leave_requests(self, user_id: str) -> List[LeaveRequestDTO]:
        def _query() -> List[LeaveRequestDTO]:
            with self._session() as session:
                rows = (
                    session.query(LeaveRequestRecord)
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
            with self._session() as session:
                row = session.get(AttendanceRecord, user_id)
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
            with self._session() as session:
                row = session.get(OnboardingRecord, user_id)
                if row is None:
                    return None
                checklist = [
                    OnboardingItemDTO(task=str(item.get("task", "")), done=bool(item.get("done")))
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
            with self._session() as session:
                rows = (
                    session.query(PayrollSummaryRecord)
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

    async def get_benefits(self, user_id: str) -> Optional[BenefitsDTO]:
        def _query() -> Optional[BenefitsDTO]:
            with self._session() as session:
                row = session.get(BenefitsRecord, user_id)
                if row is None:
                    return None
                items = [
                    BenefitItemDTO(name=str(item.get("name", "")), value=str(item.get("value", "")))
                    for item in (row.items or [])
                    if isinstance(item, dict)
                ]
                return BenefitsDTO(items=items)

        return await asyncio.to_thread(_query)

    async def get_performance(self, user_id: str) -> Optional[PerformanceReviewDTO]:
        def _query() -> Optional[PerformanceReviewDTO]:
            with self._session() as session:
                row = (
                    session.query(PerformanceReviewRecord)
                    .filter(PerformanceReviewRecord.user_id == user_id)
                    .order_by(PerformanceReviewRecord.period.desc())
                    .first()
                )
                if row is None:
                    return None
                return PerformanceReviewDTO(
                    period=row.period,
                    rating=row.rating,
                    kpi=list(row.kpi or []),
                    reviewer_user_id=row.reviewer_user_id,
                )

        return await asyncio.to_thread(_query)

    async def aclose(self) -> None:
        def _dispose() -> None:
            if self._engine is not None:
                self._engine.dispose()

        await asyncio.to_thread(_dispose)

