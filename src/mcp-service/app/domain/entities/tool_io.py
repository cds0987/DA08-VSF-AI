"""I/O contract của MCP tools.

Định nghĩa bởi SA — không sửa mà không có approval (xem docs/contracts.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ── rag_search ────────────────────────────────────────────────────────────────

@dataclass
class RagSearchInput:
    query: str
    document_ids: Optional[List[str]]  # inject từ ACL, None = chỉ public
    top_k: int = 5


# ── hr_query ──────────────────────────────────────────────────────────────────

@dataclass
class HrQueryInput:
    user_id: str   # inject từ JWT — KHÔNG để LLM tự điền
    intent: str    # 'leave_balance' | 'leave_requests' | 'attendance' | 'onboarding'


@dataclass
class LeaveBalanceDTO:
    annual_total: int
    annual_used: int
    annual_remaining: int      # = annual_total - annual_used
    sick_total: int
    sick_used: int
    sick_remaining: int        # = sick_total - sick_used


@dataclass
class LeaveRequestDTO:
    leave_type: str            # 'annual' | 'sick' | 'personal'
    start_date: str            # 'YYYY-MM-DD'
    end_date: str              # 'YYYY-MM-DD'
    days_count: int
    status: str                # 'pending' | 'approved' | 'rejected'


@dataclass
class PayrollDTO:
    period: str                # 'YYYY-MM'
    gross_salary: float
    deductions: float
    net_salary: float


@dataclass
class AttendanceDTO:
    period: str                # 'YYYY-MM'
    work_days: int
    late_count: int
    absent_count: int


@dataclass
class OnboardingItemDTO:
    task: str
    done: bool


@dataclass
class OnboardingDTO:
    status: str                          # 'in_progress' | 'completed'
    checklist: List[OnboardingItemDTO]
    completed_count: int
    total_count: int


@dataclass
class HrQueryResult:
    intent: str
    leave_balance: Optional[LeaveBalanceDTO] = None
    leave_requests: Optional[List[LeaveRequestDTO]] = None
    payroll: Optional[List[PayrollDTO]] = None          # Cao — chưa expose MVP
    attendance: Optional[AttendanceDTO] = None
    onboarding: Optional[OnboardingDTO] = None
    summary: str = ""
