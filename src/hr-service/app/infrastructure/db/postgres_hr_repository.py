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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.entities.dtos import (
    AttendanceDTO,
    BenefitItemDTO,
    BenefitsDTO,
    EmployeeDTO,
    LeaveBalanceDTO,
    LeaveRequestDTO,
    OnboardingDTO,
    OnboardingItemDTO,
    PayrollDTO,
    PerformanceReviewDTO,
)
from app.domain.leave_policy import get_policy
from app.domain.repositories.hr_repository import HrRepository
from app.domain.repositories.leave_write_repository import (
    ApproverNotConfigured,
    InsufficientLeaveBalance,
    LeaveRequestConflict,
    LeaveRequestDuplicate,
    LeaveRequestForbidden,
    LeaveRequestNotFound,
    LeaveRequestOverlapWarning,
    LeaveWriteRepository,
)
from app.infrastructure.db.models import (
    AttendanceRecord,
    BenefitsRecord,
    DepartmentRecord,
    EmployeeRecord,
    LeaveBalanceRecord,
    LeaveRequestRecord,
    OnboardingRecord,
    PayrollSummaryRecord,
    PerformanceReviewRecord,
)

_TERMINAL_STATES = {"cancelled", "rejected"}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_date(value: object) -> datetime.date:
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value))


def _req_to_dict(rec: LeaveRequestRecord) -> dict:
    return {
        "id": rec.id,
        "user_id": rec.user_id,
        "leave_type": rec.leave_type,
        "start_date": str(rec.start_date),
        "end_date": str(rec.end_date),
        "days_count": rec.days_count,
        "status": rec.status,
        "reason": rec.reason,
        "approver_user_id": rec.approver_user_id,
        "approved_at": rec.approved_at.isoformat() if rec.approved_at else None,
        "rejected_at": rec.rejected_at.isoformat() if rec.rejected_at else None,
        "rejected_reason": rec.rejected_reason,
        "cancelled_at": rec.cancelled_at.isoformat() if rec.cancelled_at else None,
    }


class PostgresHrRepository(HrRepository, LeaveWriteRepository):
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

    async def get_distinct_departments(self) -> list[str]:
        def _query() -> list[str]:
            with self._session() as session:
                rows = session.execute(
                    sa.select(DepartmentRecord.name)
                    .order_by(DepartmentRecord.name)
                ).scalars().all()
                if rows:
                    return list(rows)
                # Fallback: bảng departments chưa được seed → đọc từ employees
                rows = session.execute(
                    sa.select(EmployeeRecord.department)
                    .where(EmployeeRecord.department != "")
                    .distinct()
                    .order_by(EmployeeRecord.department)
                ).scalars().all()
                return list(rows)

        return await asyncio.to_thread(_query)

    async def get_employee_departments(self) -> list[dict]:
        def _query() -> list[dict]:
            with self._session() as session:
                rows = session.execute(
                    sa.select(EmployeeRecord.user_id, EmployeeRecord.department)
                    .where(EmployeeRecord.employment_status == "active")
                ).all()
                return [{"user_id": r.user_id, "department": r.department} for r in rows]

        return await asyncio.to_thread(_query)

    async def list_employees(
        self,
        department: str | None,
        employment_status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[EmployeeDTO], int]:
        def _query() -> tuple[list[EmployeeDTO], int]:
            with self._session() as session:
                filters = []
                if department:
                    filters.append(EmployeeRecord.department == department)
                if employment_status:
                    filters.append(EmployeeRecord.employment_status == employment_status)

                total_stmt = sa.select(sa.func.count()).select_from(EmployeeRecord).where(*filters)
                total = session.scalar(total_stmt) or 0

                stmt = (
                    sa.select(EmployeeRecord)
                    .where(*filters)
                    .order_by(EmployeeRecord.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
                items = [self._to_employee_dto(r) for r in session.scalars(stmt).all()]
                return items, int(total)

        return await asyncio.to_thread(_query)

    async def get_employee(self, employee_id: str) -> Optional[EmployeeDTO]:
        def _query() -> Optional[EmployeeDTO]:
            with self._session() as session:
                record = session.get(EmployeeRecord, employee_id)
                return self._to_employee_dto(record) if record else None

        return await asyncio.to_thread(_query)

    async def get_employee_by_user_id(self, user_id: str) -> Optional[EmployeeDTO]:
        def _query() -> Optional[EmployeeDTO]:
            with self._session() as session:
                stmt = sa.select(EmployeeRecord).where(EmployeeRecord.user_id == user_id)
                record = session.execute(stmt).scalar_one_or_none()
                return self._to_employee_dto(record) if record else None

        return await asyncio.to_thread(_query)

    async def update_employee(
        self,
        employee_id: str,
        employee_code: str | None,
        job_title: str | None,
        manager_user_id: str | None,
        full_name: str | None,
        phone_number: str | None,
        date_of_birth: datetime.date | None,
        hire_date: datetime.date | None,
        department: str | None,
        provided_fields: set[str],
    ) -> Optional[EmployeeDTO]:
        def _update() -> Optional[EmployeeDTO]:
            with self._session() as session:
                record = session.get(EmployeeRecord, employee_id)
                if not record:
                    return None

                if "employee_code" in provided_fields:
                    record.employee_code = employee_code
                if "job_title" in provided_fields:
                    record.job_title = job_title
                if "manager_user_id" in provided_fields:
                    record.manager_user_id = manager_user_id
                if "full_name" in provided_fields:
                    record.full_name = full_name
                if "phone_number" in provided_fields:
                    record.phone_number = phone_number
                if "date_of_birth" in provided_fields:
                    record.date_of_birth = date_of_birth
                if "hire_date" in provided_fields:
                    record.hire_date = hire_date
                if "department" in provided_fields:
                    record.department = department or ""

                record.updated_at = _now()
                try:
                    session.commit()
                except IntegrityError as exc:
                    session.rollback()
                    if "employee_code" in str(exc).lower() or "hr_svc_employees_employee_code_key" in str(exc):
                        raise ValueError("Duplicate employee_code") from exc
                    raise
                session.refresh(record)
                return self._to_employee_dto(record)

        return await asyncio.to_thread(_update)

    @staticmethod
    def _to_employee_dto(record: EmployeeRecord) -> EmployeeDTO:
        return EmployeeDTO(
            id=record.id,
            user_id=record.user_id,
            account_type=record.account_type,
            employee_code=record.employee_code,
            company_email=record.company_email,
            department=record.department,
            job_title=record.job_title,
            manager_user_id=record.manager_user_id,
            employment_status=record.employment_status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            full_name=record.full_name,
            phone_number=record.phone_number,
            date_of_birth=record.date_of_birth,
            hire_date=record.hire_date,
        )
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
        self, user_id: str, email: str, department: str, is_active: bool, account_type: str
    ) -> None:
        import uuid

        status = "active" if is_active else "inactive"

        def _upsert() -> None:
            with self._session() as session:
                # Upsert theo user_id (unique). created_at/updated_at lấy server_default.
                session.execute(
                    sa.text(
                        "INSERT INTO hr_svc.employees "
                        "(id, user_id, company_email, department, employment_status, account_type) "
                        "VALUES (:id, :uid, :email, :dept, :status, :acc_type) "
                        "ON CONFLICT (user_id) DO UPDATE SET "
                        "  company_email = EXCLUDED.company_email, "
                        "  department = EXCLUDED.department, "
                        "  employment_status = EXCLUDED.employment_status, "
                        "  account_type = EXCLUDED.account_type, "
                        "  updated_at = now()"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "uid": user_id,
                        "email": email or f"{user_id}@unknown.local",
                        "dept": department or "",
                        "status": status,
                        "acc_type": account_type,
                    },
                )
                session.commit()

        await asyncio.to_thread(_upsert)

    async def seed_demo_employees(self) -> None:
        """Dev/demo: user test (nhanvien/sep) được seed THẲNG vào user_svc.users, bỏ qua
        event UserCreated -> không có hồ sơ HR -> sếp chỉ thấy user_id. Seed employee row
        (idempotent) cho 2 user test cố định để hàng đợi duyệt hiện tên/email. Chỉ chạy
        khi APP_STAGE=develop (gọi từ lifespan)."""
        import uuid as _uuid

        # user_id TẤT ĐỊNH = uuid5 (khớp seed_user.py + HR_DEFAULT_APPROVER).
        demo = [
            ("0ee316e0-075f-530e-914a-884e494f3d4e", "nhanvien@company.com", "Nhân viên Demo", "Engineering", "Nhân viên"),
            ("2dc14f72-64f6-5361-87aa-15e859f7cf90", "sep@company.com", "Sếp Demo", "Engineering", "Quản lý"),
        ]

        def _seed() -> None:
            with self._session() as session:
                for uid, email, name, dept, title in demo:
                    session.execute(
                        sa.text(
                            "INSERT INTO hr_svc.employees "
                            "(id, user_id, company_email, full_name, department, job_title, "
                            " employment_status, account_type) "
                            "VALUES (:id, :uid, :email, :name, :dept, :title, 'active', 'internal') "
                            "ON CONFLICT (user_id) DO UPDATE SET "
                            "  full_name = COALESCE(hr_svc.employees.full_name, EXCLUDED.full_name), "
                            "  job_title = COALESCE(hr_svc.employees.job_title, EXCLUDED.job_title), "
                            "  updated_at = now()"
                        ),
                        {"id": str(_uuid.uuid4()), "uid": uid, "email": email,
                         "name": name, "dept": dept, "title": title},
                    )
                session.commit()

        await asyncio.to_thread(_seed)

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
                row = session.execute(
                    sa.select(AttendanceRecord)
                    .where(AttendanceRecord.user_id == user_id)
                    .order_by(AttendanceRecord.period.desc())
                    .limit(1)
                ).scalar_one_or_none()
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
                            # PK composite (user_id, period) -> conflict target phải khớp,
                            # KHÔNG có unique constraint trên (user_id) đơn cột.
                            "ON CONFLICT (user_id, period) DO NOTHING"
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

    # ────────────────────────── LEAVE WRITE ──────────────────────────
    # Pattern giống read: sync SQLAlchemy bọc asyncio.to_thread, session per call.
    # Mỗi thao tác đổi-trạng-thái = 1 transaction: SELECT ... FOR UPDATE khóa đơn
    # (và balance khi trừ/hoàn) -> atomic, chống đua. Thứ tự khóa: leave_requests
    # trước, leave_balance sau -> tránh deadlock.

    @staticmethod
    def _resolve_approver(session: Session, user_id: str, default_approver: str) -> str:
        row = (
            session.query(EmployeeRecord.manager_user_id)
            .filter(EmployeeRecord.user_id == user_id)
            .first()
        )
        manager = row[0] if row else None
        approver = (manager or "").strip() or (default_approver or "").strip()
        if not approver:
            raise ApproverNotConfigured(
                "không resolve được approver: nhân viên không có manager và "
                "HR_DEFAULT_APPROVER rỗng"
            )
        return approver

    @staticmethod
    def _adjust_balance(session: Session, owner_id: str, leave_type: str, delta_days: int) -> None:
        """delta_days > 0 = trừ (duyệt); < 0 = hoàn (hủy/sửa-approved).

        Định tuyến quỹ theo Leave Type Registry (4 rổ luật LĐ VN):
        - deduct_pool="annual" -> trừ quỹ phép năm.
        - deduct_pool="sick"   -> trừ quỹ nghỉ ốm (BHXH cap).
        - None (rổ 2 sự kiện / rổ 4 không lương / thai sản) -> KHÔNG trừ quỹ.
        Trừ vượt quỹ -> InsufficientLeaveBalance."""
        policy = get_policy(leave_type)
        pool = policy.deduct_pool if policy else "annual"  # type lạ -> mặc định an toàn
        if pool is None:
            return
        bal = (
            session.query(LeaveBalanceRecord)
            .filter(LeaveBalanceRecord.user_id == owner_id)
            .with_for_update()
            .first()
        )
        if bal is None:
            # Không có hồ sơ phép -> không thể trừ. Hoàn (delta<0) cũng vô nghĩa -> bỏ qua.
            if delta_days > 0:
                raise InsufficientLeaveBalance("nhân viên chưa có hồ sơ hạn mức phép")
            return
        if pool == "annual":
            new_used = bal.annual_leave_used + delta_days
            if new_used > bal.annual_leave_total:
                raise InsufficientLeaveBalance("vượt quỹ phép năm còn lại")
            bal.annual_leave_used = max(0, new_used)
        else:  # sick
            new_used = bal.sick_leave_used + delta_days
            if new_used > bal.sick_leave_total:
                raise InsufficientLeaveBalance("vượt quỹ nghỉ ốm còn lại")
            bal.sick_leave_used = max(0, new_used)
        bal.updated_at = _now()

    def _find_by_key(self, session: Session, idempotency_key: Optional[str]):
        if not idempotency_key:
            return None
        return (
            session.query(LeaveRequestRecord)
            .filter(LeaveRequestRecord.idempotency_key == idempotency_key)
            .first()
        )

    @staticmethod
    def _norm_reason(reason: Optional[str]) -> str:
        return (reason or "").strip().casefold()

    def _find_active_duplicate(
        self,
        session: Session,
        *,
        user_id: str,
        leave_type: str,
        start: datetime.date,
        end: datetime.date,
        reason: str,
    ):
        """Đơn active (pending/approved) TRÙNG TOÀN BỘ: cùng user + loại + đúng khoảng
        ngày + cùng lý do (chuẩn hoá). Khác bất kỳ field nào -> không phải trùng."""
        candidates = (
            session.query(LeaveRequestRecord)
            .filter(
                LeaveRequestRecord.user_id == user_id,
                LeaveRequestRecord.leave_type == leave_type,
                LeaveRequestRecord.start_date == start,
                LeaveRequestRecord.end_date == end,
                LeaveRequestRecord.status.in_(("pending", "approved")),
            )
            .all()
        )
        target = self._norm_reason(reason)
        for rec in candidates:
            if self._norm_reason(rec.reason) == target:
                return rec
        return None

    def _find_overlaps(
        self,
        session: Session,
        *,
        user_id: str,
        start: datetime.date,
        end: datetime.date,
    ) -> list[LeaveRequestRecord]:
        """Đơn active (pending/approved) của user CHỒNG khoảng ngày [start, end]
        (rec.start <= end AND rec.end >= start). Dùng để cảnh báo khi user có thể
        đã quên đặt đơn cùng/đè ngày."""
        return (
            session.query(LeaveRequestRecord)
            .filter(
                LeaveRequestRecord.user_id == user_id,
                LeaveRequestRecord.status.in_(("pending", "approved")),
                LeaveRequestRecord.start_date <= end,
                LeaveRequestRecord.end_date >= start,
            )
            .order_by(LeaveRequestRecord.start_date)
            .all()
        )

    def _new_request(
        self,
        session: Session,
        *,
        user_id: str,
        leave_type: str,
        start: datetime.date,
        end: datetime.date,
        reason: str,
        approver: str,
        idempotency_key: Optional[str],
    ) -> LeaveRequestRecord:
        now = _now()
        rec = LeaveRequestRecord(
            id=str(uuid.uuid4()),
            user_id=user_id,
            employee_id=None,
            leave_type=leave_type,
            start_date=start,
            end_date=end,
            days_count=(end - start).days + 1,
            status="pending",
            reason=reason or None,
            approver_user_id=approver,
            idempotency_key=idempotency_key or None,
            created_at=now,
            updated_at=now,
        )
        session.add(rec)
        return rec

    async def create_leave_request(
        self,
        *,
        user_id: str,
        leave_type: str,
        start_date: str,
        end_date: str,
        reason: str,
        default_approver: str,
        idempotency_key: Optional[str] = None,
        confirm_overlap: bool = False,
    ) -> dict:
        start, end = _parse_date(start_date), _parse_date(end_date)

        def _create() -> dict:
            with self._session() as session:
                existing = self._find_by_key(session, idempotency_key)
                if existing is not None:
                    return {"request": _req_to_dict(existing), "created": False}
                dup = self._find_active_duplicate(
                    session,
                    user_id=user_id,
                    leave_type=leave_type,
                    start=start,
                    end=end,
                    reason=reason,
                )
                if dup is not None:
                    status_vi = "đang chờ duyệt" if dup.status == "pending" else "đã được duyệt"
                    raise LeaveRequestDuplicate(
                        f"Bạn đã có một đơn nghỉ y hệt ({status_vi}) cho khoảng ngày này — "
                        f"không tạo thêm để tránh trùng.",
                        existing=_req_to_dict(dup),
                    )
                # Chồng ngày nhưng khác nội dung: user có thể quên -> cảnh báo, để user
                # xác nhận (confirm_overlap) thay vì tạo mù hoặc chặn cứng.
                if not confirm_overlap:
                    overlaps = self._find_overlaps(
                        session, user_id=user_id, start=start, end=end
                    )
                    if overlaps:
                        raise LeaveRequestOverlapWarning(
                            "Bạn đã có đơn nghỉ trùng/đè lên khoảng ngày này. Kiểm tra lại "
                            "bên dưới — nếu vẫn muốn tạo đơn mới, hãy xác nhận.",
                            existing=[_req_to_dict(o) for o in overlaps],
                        )
                approver = self._resolve_approver(session, user_id, default_approver)
                rec = self._new_request(
                    session,
                    user_id=user_id,
                    leave_type=leave_type,
                    start=start,
                    end=end,
                    reason=reason,
                    approver=approver,
                    idempotency_key=idempotency_key,
                )
                try:
                    session.commit()
                except IntegrityError:
                    # Đua trên idempotency_key: 1 request khác đã tạo trước -> trả nó.
                    session.rollback()
                    existing = self._find_by_key(session, idempotency_key)
                    if existing is not None:
                        return {"request": _req_to_dict(existing), "created": False}
                    raise
                return {"request": _req_to_dict(rec), "created": True}

        return await asyncio.to_thread(_create)

    async def update_leave_request(
        self,
        *,
        user_id: str,
        request_id: str,
        leave_type: str,
        start_date: str,
        end_date: str,
        reason: str,
        default_approver: str,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        start, end = _parse_date(start_date), _parse_date(end_date)

        def _update() -> dict:
            with self._session() as session:
                # Retry sửa-approved đã thành công trước đó -> đơn mới mang key -> trả nó.
                prior = self._find_by_key(session, idempotency_key)
                if prior is not None and prior.id != request_id:
                    return {"request": _req_to_dict(prior), "mode": "replaced",
                            "replaced_request": None}
                rec = (
                    session.query(LeaveRequestRecord)
                    .filter(LeaveRequestRecord.id == request_id)
                    .with_for_update()
                    .first()
                )
                if rec is None:
                    raise LeaveRequestNotFound(request_id)
                if rec.user_id != user_id:
                    raise LeaveRequestForbidden("chỉ chủ đơn được sửa")
                now = _now()
                if rec.status == "pending":
                    rec.leave_type = leave_type
                    rec.start_date = start
                    rec.end_date = end
                    rec.days_count = (end - start).days + 1
                    rec.reason = reason or None
                    rec.updated_at = now
                    session.commit()
                    return {"request": _req_to_dict(rec), "mode": "updated",
                            "replaced_request": None}
                if rec.status == "approved":
                    # Hủy đơn cũ + HOÀN phép + tạo đơn pending mới (quy trình duyệt lại).
                    self._adjust_balance(session, rec.user_id, rec.leave_type, -rec.days_count)
                    rec.status = "cancelled"
                    rec.cancelled_at = now
                    rec.updated_at = now
                    old_dict = _req_to_dict(rec)
                    approver = self._resolve_approver(session, user_id, default_approver)
                    new = self._new_request(
                        session,
                        user_id=user_id,
                        leave_type=leave_type,
                        start=start,
                        end=end,
                        reason=reason,
                        approver=approver,
                        idempotency_key=idempotency_key,
                    )
                    session.commit()
                    return {"request": _req_to_dict(new), "mode": "replaced",
                            "replaced_request": old_dict}
                raise LeaveRequestConflict(f"không sửa được đơn ở trạng thái {rec.status}")

        return await asyncio.to_thread(_update)

    async def cancel_leave_request(self, *, user_id: str, request_id: str) -> dict:
        def _cancel() -> dict:
            with self._session() as session:
                rec = (
                    session.query(LeaveRequestRecord)
                    .filter(LeaveRequestRecord.id == request_id)
                    .with_for_update()
                    .first()
                )
                if rec is None:
                    raise LeaveRequestNotFound(request_id)
                if rec.user_id != user_id:
                    raise LeaveRequestForbidden("chỉ chủ đơn được hủy")
                if rec.status in _TERMINAL_STATES:
                    # Đã hủy/từ chối -> no-op idempotent, không lỗi.
                    return {"request": _req_to_dict(rec), "changed": False}
                if rec.status == "approved":
                    self._adjust_balance(session, rec.user_id, rec.leave_type, -rec.days_count)
                now = _now()
                rec.status = "cancelled"
                rec.cancelled_at = now
                rec.updated_at = now
                session.commit()
                return {"request": _req_to_dict(rec), "changed": True}

        return await asyncio.to_thread(_cancel)

    async def list_pending_approval(self, approver_user_id: str) -> list:
        def _list() -> list:
            with self._session() as session:
                rows = (
                    session.query(LeaveRequestRecord)
                    .filter(
                        LeaveRequestRecord.approver_user_id == approver_user_id,
                        LeaveRequestRecord.status == "pending",
                    )
                    .order_by(LeaveRequestRecord.created_at.asc())
                    .all()
                )
                return [self._enrich_approval(session, row) for row in rows]

        return await asyncio.to_thread(_list)

    def _enrich_approval(self, session: Session, row: LeaveRequestRecord) -> dict:
        """Đính kèm GỢI Ý QUYẾT ĐỊNH cho sếp: số phép còn lại của NV (annual/sick;
        personal không trừ quỹ -> None) + cờ trùng lịch (đơn active khác của cùng NV
        đè khoảng ngày). Giúp sếp duyệt nhanh, không phải tra cứu tay."""
        item = _req_to_dict(row)
        remaining: int | None = None
        total: int | None = None
        bal = session.get(LeaveBalanceRecord, row.user_id)
        policy = get_policy(row.leave_type)
        pool = policy.deduct_pool if policy else None
        if bal is not None and pool == "annual":
            remaining = bal.annual_leave_total - bal.annual_leave_used
            total = bal.annual_leave_total
        elif bal is not None and pool == "sick":
            remaining = bal.sick_leave_total - bal.sick_leave_used
            total = bal.sick_leave_total
        # Rổ 2 (sự kiện) / rổ 4 (không lương) / thai sản: không trừ quỹ -> remaining=None.
        conflicts = (
            session.query(LeaveRequestRecord)
            .filter(
                LeaveRequestRecord.user_id == row.user_id,
                LeaveRequestRecord.id != row.id,
                LeaveRequestRecord.status.in_(("pending", "approved")),
                LeaveRequestRecord.start_date <= row.end_date,
                LeaveRequestRecord.end_date >= row.start_date,
            )
            .count()
        )
        item["employee_leave_remaining"] = remaining
        item["employee_leave_total"] = total
        item["has_conflict"] = conflicts > 0
        # Danh tính nhân viên (từ bảng employees) -> sếp thấy tên/email thay user_id.
        emp = (
            session.query(EmployeeRecord)
            .filter(EmployeeRecord.user_id == row.user_id)
            .first()
        )
        item["employee_name"] = emp.full_name if emp else None
        item["employee_email"] = emp.company_email if emp else None
        item["employee_department"] = emp.department if emp else None
        item["employee_job_title"] = emp.job_title if emp else None
        return item

    async def update_leave_status(
        self,
        *,
        request_id: str,
        approver_user_id: str,
        action: str,
        reason: Optional[str] = None,
    ) -> dict:
        def _decide() -> dict:
            with self._session() as session:
                rec = (
                    session.query(LeaveRequestRecord)
                    .filter(LeaveRequestRecord.id == request_id)
                    .with_for_update()
                    .first()
                )
                if rec is None:
                    raise LeaveRequestNotFound(request_id)
                if rec.approver_user_id != approver_user_id:
                    raise LeaveRequestForbidden("không phải người duyệt của đơn này")
                if rec.status != "pending":
                    raise LeaveRequestConflict(f"đơn không ở trạng thái pending ({rec.status})")
                now = _now()
                if action == "approve":
                    # Trừ balance TRƯỚC (có thể raise -> rollback, đơn giữ pending).
                    self._adjust_balance(session, rec.user_id, rec.leave_type, rec.days_count)
                    rec.status = "approved"
                    rec.approved_at = now
                elif action == "reject":
                    rec.status = "rejected"
                    rec.rejected_at = now
                    rec.rejected_reason = reason or None
                else:
                    raise ValueError(f"action không hợp lệ: {action}")
                rec.updated_at = now
                session.commit()
                return {"request": _req_to_dict(rec)}

        return await asyncio.to_thread(_decide)

    async def aclose(self) -> None:
        def _dispose() -> None:
            if self._engine is not None:
                self._engine.dispose()

        await asyncio.to_thread(_dispose)

