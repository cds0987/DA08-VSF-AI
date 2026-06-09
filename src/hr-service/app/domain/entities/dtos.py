from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HrQueryInput:
    user_id: str
    intent: str


@dataclass(frozen=True)
class LeaveBalanceDTO:
    annual_total: int
    annual_used: int
    annual_remaining: int
    sick_total: int
    sick_used: int
    sick_remaining: int


@dataclass(frozen=True)
class LeaveRequestDTO:
    leave_type: str
    start_date: str
    end_date: str
    days_count: int
    status: str


@dataclass(frozen=True)
class PayrollDTO:
    period: str
    gross_salary: float
    deductions: float
    net_salary: float


@dataclass(frozen=True)
class AttendanceDTO:
    period: str
    work_days: int
    late_count: int
    absent_count: int


@dataclass(frozen=True)
class OnboardingItemDTO:
    task: str
    done: bool


@dataclass(frozen=True)
class OnboardingDTO:
    status: str
    checklist: list[OnboardingItemDTO] = field(default_factory=list)
    completed_count: int = 0
    total_count: int = 0


@dataclass(frozen=True)
class HrQueryResult:
    intent: str
    data: dict[str, Any]
    summary: str

