from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities.dtos import (
    AttendanceDTO,
    BenefitsDTO,
    EmployeeDTO,
    LeaveBalanceDTO,
    LeaveRequestDTO,
    OnboardingDTO,
    PayrollDTO,
    PerformanceReviewDTO,
)


class HrRepository(ABC):
    @abstractmethod
    async def ping(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_employees(
        self,
        department: str | None,
        employment_status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[EmployeeDTO], int]:
        raise NotImplementedError

    @abstractmethod
    async def get_employee(self, employee_id: str) -> Optional[EmployeeDTO]:
        raise NotImplementedError

    @abstractmethod
    async def get_employee_by_user_id(self, user_id: str) -> Optional[EmployeeDTO]:
        raise NotImplementedError

    @abstractmethod
    async def update_employee(
        self,
        employee_id: str,
        employee_code: str | None,
        job_title: str | None,
        manager_user_id: str | None,
        provided_fields: set[str],
    ) -> Optional[EmployeeDTO]:
        raise NotImplementedError

    @abstractmethod
    async def get_leave_balance(self, user_id: str) -> Optional[LeaveBalanceDTO]:
        raise NotImplementedError

    @abstractmethod
    async def ensure_leave_balance(
        self, user_id: str, annual_total: int, sick_total: int
    ) -> None:
        """Tạo bản ghi leave_balance với hạn mức mặc định cho trước nếu chưa có
        (idempotent). Lưới an toàn cho user chưa được đồng bộ qua event user.created.
        Hạn mức do caller truyền vào (từ HrSettings), KHÔNG hardcode trong repo/migration."""
        raise NotImplementedError

    @abstractmethod
    async def upsert_employee_from_user(
        self, user_id: str, email: str, department: str, is_active: bool, account_type: str
    ) -> None:
        """Upsert hồ sơ nhân viên từ event user.* (idempotent). KHÔNG đọc DB user-service;
        chỉ ghi từ payload event."""
        raise NotImplementedError

    @abstractmethod
    async def get_leave_requests(self, user_id: str) -> List[LeaveRequestDTO]:
        raise NotImplementedError

    @abstractmethod
    async def get_attendance(self, user_id: str) -> Optional[AttendanceDTO]:
        raise NotImplementedError

    @abstractmethod
    async def get_onboarding(self, user_id: str) -> Optional[OnboardingDTO]:
        raise NotImplementedError

    @abstractmethod
    async def get_payroll(self, user_id: str) -> List[PayrollDTO]:
        raise NotImplementedError

    @abstractmethod
    async def get_benefits(self, user_id: str) -> Optional[BenefitsDTO]:
        raise NotImplementedError

    @abstractmethod
    async def get_performance(self, user_id: str) -> Optional[PerformanceReviewDTO]:
        raise NotImplementedError

    async def provision_mock(self, intent: str, user_id: str) -> None:
        """Dev-only: tự sinh 1 bản ghi mock (idempotent) cho `intent` của user chưa có
        hồ sơ — phục vụ test end-to-end khi APP_STAGE=develop. Mặc định NO-OP (CHỈ
        Postgres impl thật) -> KHÔNG @abstractmethod để fake repo trong test không vỡ."""
        return None

    async def get_distinct_departments(self) -> list[str]:
        """Trả danh sách department duy nhất đang tồn tại trong employees (sorted).
        Mặc định [] — override trong PostgresHrRepository."""
        return []

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError

