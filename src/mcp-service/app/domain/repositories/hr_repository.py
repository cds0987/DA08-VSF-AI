"""HrRepository ABC — đọc schema hr_mock trong mcp_db.

LUÔN filter WHERE user_id (inject từ JWT, không tin LLM).
Implement: app.infrastructure.db.postgres_hr_repository.PostgresHrRepository
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from app.domain.entities.tool_io import (
    AttendanceDTO,
    LeaveBalanceDTO,
    LeaveRequestDTO,
    OnboardingDTO,
    PayrollDTO,
)


class HrRepository(ABC):

    @abstractmethod
    async def ping(self) -> None:
        """SELECT 1 — startup verify fail-closed."""

    @abstractmethod
    async def get_leave_balance(self, user_id: str) -> Optional[LeaveBalanceDTO]:
        """hr_mock.leave_balance WHERE user_id."""

    @abstractmethod
    async def get_leave_requests(self, user_id: str) -> List[LeaveRequestDTO]:
        """hr_mock.leave_requests WHERE user_id ORDER BY created_at DESC."""

    @abstractmethod
    async def get_attendance(self, user_id: str) -> Optional[AttendanceDTO]:
        """hr_mock.attendance WHERE user_id."""

    @abstractmethod
    async def get_onboarding(self, user_id: str) -> Optional[OnboardingDTO]:
        """hr_mock.onboarding WHERE user_id."""

    @abstractmethod
    async def get_payroll(self, user_id: str) -> List[PayrollDTO]:
        """hr_mock.payroll_summary WHERE user_id ORDER BY period DESC. Chưa expose MVP."""

    @abstractmethod
    async def aclose(self) -> None:
        """Giải phóng connection pool."""
