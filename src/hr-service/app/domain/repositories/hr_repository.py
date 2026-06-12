from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities.dtos import (
    AttendanceDTO,
    BenefitsDTO,
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
        self, user_id: str, email: str, department: str, is_active: bool
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

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError

