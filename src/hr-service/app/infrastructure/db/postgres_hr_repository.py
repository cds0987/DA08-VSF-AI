from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import uuid
from typing import List, Optional

# Namespace cố định để sinh id mock DETERMINISTIC (uuid5) — luôn 36 ký tự, vừa cột
# VARCHAR(36), idempotent theo (intent,user_id). KHÔNG hardcode prefix+user_id (vượt 36).
_MOCK_NS = uuid.UUID("00000000-0000-5000-8000-000000000abc")

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

    async def ensure_leave_balance(
        self, user_id: str, annual_total: int, sick_total: int
    ) -> None:
        def _ensure() -> None:
            with self._session() as session:
                # Chèn hạn mức tường minh từ config (annual/sick); used lấy server_default 0.
                # ON CONFLICT DO NOTHING -> idempotent, an toàn khi gọi đua.
                session.execute(
                    sa.text(
                        "INSERT INTO hr_svc.leave_balance "
                        "(user_id, annual_leave_total, sick_leave_total) "
                        "VALUES (:uid, :annual, :sick) "
                        "ON CONFLICT (user_id) DO NOTHING"
                    ),
                    {"uid": user_id, "annual": annual_total, "sick": sick_total},
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

    async def provision_mock(self, intent: str, user_id: str) -> None:
        """Dev-only (APP_STAGE=develop): sinh 1 bản ghi mock idempotent cho intent của
        user chưa có hồ sơ. Giá trị DETERMINISTIC theo user_id (gọi lại ra y nhau).
        ON CONFLICT DO NOTHING -> an toàn race + không đè data thật. Read path only;
        leave_balance đã có ensure_leave_balance riêng nên KHÔNG xử ở đây."""
        seed = int(hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:8], 16)
        period = datetime.date.today().strftime("%Y-%m")

        def _provision() -> None:
            with self._session() as session:
                if intent == "attendance":
                    session.execute(
                        sa.text(
                            "INSERT INTO hr_svc.attendance "
                            "(user_id, period, work_days, late_count, absent_count) "
                            "VALUES (:uid, :period, :wd, :late, :absent) "
                            "ON CONFLICT (user_id) DO NOTHING"
                        ),
                        {
                            "uid": user_id,
                            "period": period,
                            "wd": 18 + seed % 5,
                            "late": seed % 3,
                            "absent": seed % 2,
                        },
                    )
                elif intent == "onboarding":
                    checklist = [
                        {"task": "Nhan laptop va the", "done": True},
                        {"task": "Hoan thanh dao tao bao mat", "done": True},
                        {"task": "Gap go team", "done": True},
                    ]
                    session.execute(
                        sa.text(
                            "INSERT INTO hr_svc.onboarding (user_id, status, checklist) "
                            "VALUES (:uid, 'completed', CAST(:cl AS jsonb)) "
                            "ON CONFLICT (user_id) DO NOTHING"
                        ),
                        {"uid": user_id, "cl": json.dumps(checklist)},
                    )
                elif intent == "benefits":
                    items = [
                        {"name": "Bao hiem suc khoe", "value": "Goi A"},
                        {"name": "Phu cap an trua", "value": "30 USD/thang"},
                    ]
                    session.execute(
                        sa.text(
                            "INSERT INTO hr_svc.benefits (user_id, items) "
                            "VALUES (:uid, CAST(:items AS jsonb)) "
                            "ON CONFLICT (user_id) DO NOTHING"
                        ),
                        {"uid": user_id, "items": json.dumps(items)},
                    )
                elif intent == "payroll":
                    gross = 1000 + seed % 1000
                    deductions = round(gross * 0.15, 2)
                    session.execute(
                        sa.text(
                            "INSERT INTO hr_svc.payroll_summary "
                            "(id, user_id, period, gross_salary, deductions, net_salary) "
                            "VALUES (:id, :uid, :period, :gross, :ded, :net) "
                            "ON CONFLICT (user_id, period) DO NOTHING"
                        ),
                        {
                            "id": str(uuid.uuid5(_MOCK_NS, f"pay-{user_id}")),
                            "uid": user_id,
                            "period": period,
                            "gross": gross,
                            "ded": deductions,
                            "net": round(gross - deductions, 2),
                        },
                    )
                elif intent == "performance":
                    kpi = [{"name": "Hoan thanh cong viec", "score": 80 + seed % 20}]
                    session.execute(
                        sa.text(
                            "INSERT INTO hr_svc.performance_reviews "
                            "(id, user_id, period, rating, kpi, reviewer_user_id) "
                            "VALUES (:id, :uid, :period, :rating, CAST(:kpi AS jsonb), NULL) "
                            "ON CONFLICT (user_id, period) DO NOTHING"
                        ),
                        {
                            "id": str(uuid.uuid5(_MOCK_NS, f"perf-{user_id}")),
                            "uid": user_id,
                            "period": period,
                            "rating": "Dat",
                            "kpi": json.dumps(kpi),
                        },
                    )
                elif intent == "leave_requests":
                    # Chỉ seed dữ liệu ĐỌC (1 đơn mẫu đã duyệt); tạo đơn thật vẫn là T4.
                    session.execute(
                        sa.text(
                            "INSERT INTO hr_svc.leave_requests "
                            "(id, user_id, employee_id, leave_type, start_date, end_date, "
                            " days_count, status, reason, approver_user_id, approved_at) "
                            "VALUES (:id, :uid, NULL, 'annual', :start, :end, 1, 'approved', "
                            " NULL, :uid, now()) "
                            "ON CONFLICT (id) DO NOTHING"
                        ),
                        {
                            "id": str(uuid.uuid5(_MOCK_NS, f"leave-{user_id}")),
                            "uid": user_id,
                            "start": f"{period}-10",
                            "end": f"{period}-10",
                        },
                    )
                else:
                    return
                session.commit()

        await asyncio.to_thread(_provision)

    async def aclose(self) -> None:
        def _dispose() -> None:
            if self._engine is not None:
                self._engine.dispose()

        await asyncio.to_thread(_dispose)

