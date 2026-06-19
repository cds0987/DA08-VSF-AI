from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.domain.entities.dtos import (
    AttendanceDTO,
    EmployeeDTO,
    LeaveBalanceDTO,
    LeaveRequestDTO,
    PayrollDTO,
    PerformanceReviewDTO,
)
from app.domain.repositories.hr_repository import HrRepository


@dataclass(frozen=True)
class EmployeeDetailsDTO:
    """Hồ sơ nhân viên đầy đủ cho trang Employee Management: ghép profile với các
    bản ghi HR phụ thuộc (lương, ngày nghỉ, chấm công, hiệu suất). Các nhánh thiếu
    dữ liệu trả None/[] thay vì lỗi để UI render được phần còn lại."""

    employee: EmployeeDTO
    leave_balance: LeaveBalanceDTO | None
    leave_requests: list[LeaveRequestDTO]
    attendance: AttendanceDTO | None
    payroll: PayrollDTO | None
    performance: PerformanceReviewDTO | None


class GetEmployeeDetailsUseCase:
    def __init__(self, repo: HrRepository) -> None:
        self.repo = repo

    async def execute(self, employee_id: str) -> EmployeeDetailsDTO | None:
        employee = await self.repo.get_employee(employee_id)
        if employee is None:
            return None

        user_id = employee.user_id
        (
            leave_balance,
            leave_requests,
            attendance,
            payroll,
            performance,
        ) = await asyncio.gather(
            self.repo.get_leave_balance(user_id),
            self.repo.get_leave_requests(user_id),
            self.repo.get_attendance(user_id),
            self.repo.get_payroll(user_id),
            self.repo.get_performance(user_id),
        )

        return EmployeeDetailsDTO(
            employee=employee,
            leave_balance=leave_balance,
            # 5 đơn gần nhất (repo đã sắp xếp created_at desc)
            leave_requests=leave_requests[:5],
            attendance=attendance,
            # payroll repo trả list theo kỳ desc -> lấy kỳ mới nhất
            payroll=payroll[0] if payroll else None,
            performance=performance,
        )
