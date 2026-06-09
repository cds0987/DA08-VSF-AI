"""Unit tests cho HrQueryTool.

Dùng FakeHrRepository inject qua monkeypatch — không cần Postgres thật.
Test bắt buộc có: happy path mỗi intent + cross-user isolation + unknown user.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

import pytest

from app.core.config import McpSettings
from app.domain.entities.tool_io import (
    AttendanceDTO,
    LeaveBalanceDTO,
    LeaveRequestDTO,
    OnboardingDTO,
    OnboardingItemDTO,
)
from app.domain.repositories.hr_repository import HrRepository

# ── Seed UUIDs (khớp với migration 0001_create_hr_schema) ────────────────────
USER_HR = "11111111-1111-4111-8111-111111111111"
USER_FINANCE = "22222222-2222-4222-8222-222222222222"
USER_UNKNOWN = "33333333-3333-4333-8333-333333333333"


# ── FakeHrRepository ──────────────────────────────────────────────────────────

class FakeHrRepository(HrRepository):
    """In-memory stub dùng cho unit test — không cần DB."""

    async def ping(self) -> None:
        return

    async def get_leave_balance(self, user_id: str) -> Optional[LeaveBalanceDTO]:
        data = {
            USER_HR:      LeaveBalanceDTO(12, 4, 8, 10, 1, 9),
            USER_FINANCE: LeaveBalanceDTO(12, 7, 5, 10, 0, 10),
        }
        return data.get(user_id)

    async def get_leave_requests(self, user_id: str) -> List[LeaveRequestDTO]:
        data = {
            USER_HR: [
                LeaveRequestDTO("annual", "2026-06-10", "2026-06-11", 2, "approved"),
                LeaveRequestDTO("sick",   "2026-06-18", "2026-06-18", 1, "pending"),
            ],
            USER_FINANCE: [
                LeaveRequestDTO("annual", "2026-06-18", "2026-06-18", 1, "pending"),
            ],
        }
        return data.get(user_id, [])

    async def get_attendance(self, user_id: str) -> Optional[AttendanceDTO]:
        data = {
            USER_HR:      AttendanceDTO("2026-06", 20, 1, 0),
            USER_FINANCE: AttendanceDTO("2026-06", 19, 2, 1),
        }
        return data.get(user_id)

    async def get_onboarding(self, user_id: str) -> Optional[OnboardingDTO]:
        data = {
            USER_HR: OnboardingDTO(
                "completed",
                [
                    OnboardingItemDTO("Nhận laptop và thẻ", True),
                    OnboardingItemDTO("Hoàn thành đào tạo bảo mật", True),
                    OnboardingItemDTO("Gặp gỡ team", True),
                ],
                3, 3,
            ),
            USER_FINANCE: OnboardingDTO(
                "in_progress",
                [
                    OnboardingItemDTO("Nhận laptop và thẻ", True),
                    OnboardingItemDTO("Hoàn thành đào tạo bảo mật", False),
                    OnboardingItemDTO("Gặp gỡ team", False),
                ],
                1, 3,
            ),
        }
        return data.get(user_id)

    async def get_payroll(self, user_id: str) -> list:
        return []

    async def aclose(self) -> None:
        return


# ── helpers ───────────────────────────────────────────────────────────────────

class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator


def _make_tool(monkeypatch) -> tuple:
    """Trả về (mcp, hr_query_fn) với FakeHrRepository inject."""
    from app.tools import hr_query as hr_module

    fake_repo = FakeHrRepository()
    monkeypatch.setattr(hr_module, "_build_hr_repository", lambda _url: fake_repo)

    settings = McpSettings(
        host="0.0.0.0", port=8003, log_level="INFO", app_env="development",
        internal_token="", provider="qdrant", collection="rag_chatbot",
        embed_model="offline", dimension=256, url="", api_key="",
        embed_base_url="", embed_api_key="", rerank_impl="none",
        rerank_model="gpt-4o-mini", rerank_base_url="", rerank_api_key="",
        rerank_timeout_seconds=30.0, rerank_batch_size=8,
        rerank_passage_chars=800, top_k_candidates=20,
        rerank_top_k=3, rerank_threshold=0.6, options={},
    )
    from app.tools.hr_query import HrQueryTool
    tool = HrQueryTool(settings, {"params": {"database_url": "postgresql://ignored"}})
    mcp = FakeMCP()
    tool.register(mcp)
    return mcp, mcp.tools["hr_query"]


# ── happy path ────────────────────────────────────────────────────────────────

def test_leave_balance_shape_and_summary(monkeypatch) -> None:
    _, fn = _make_tool(monkeypatch)
    result = asyncio.run(fn(USER_HR, "leave_balance"))

    assert result["intent"] == "leave_balance"
    assert result["data"] == {
        "annual_total": 12, "annual_used": 4, "annual_remaining": 8,
        "sick_total": 10,   "sick_used": 1,  "sick_remaining": 9,
    }
    assert "Bạn còn 8 ngày phép năm" in result["summary"]
    assert "9 ngày phép ốm" in result["summary"]
    # không có alias key thừa
    assert set(result.keys()) == {"intent", "data", "summary"}


def test_leave_requests_shape_and_summary(monkeypatch) -> None:
    _, fn = _make_tool(monkeypatch)
    result = asyncio.run(fn(USER_HR, "leave_requests"))

    assert result["intent"] == "leave_requests"
    requests = result["data"]["requests"]
    assert len(requests) == 2
    assert requests[0]["leave_type"] == "annual"
    assert requests[0]["start_date"] == "2026-06-10"   # đúng tên field (không phải from_date)
    assert requests[0]["end_date"] == "2026-06-11"
    assert requests[0]["days_count"] == 2
    assert "Đơn nghỉ gần nhất" in result["summary"]
    assert set(result.keys()) == {"intent", "data", "summary"}


def test_attendance_shape_and_summary(monkeypatch) -> None:
    _, fn = _make_tool(monkeypatch)
    result = asyncio.run(fn(USER_HR, "attendance"))

    assert result["intent"] == "attendance"
    assert result["data"]["work_days"] == 20
    assert result["data"]["late_count"] == 1
    assert result["data"]["absent_count"] == 0
    assert "20 ngày công" in result["summary"]
    assert set(result.keys()) == {"intent", "data", "summary"}


def test_onboarding_shape_and_summary(monkeypatch) -> None:
    _, fn = _make_tool(monkeypatch)
    result = asyncio.run(fn(USER_HR, "onboarding"))

    assert result["intent"] == "onboarding"
    assert result["data"]["status"] == "completed"
    assert result["data"]["completed_count"] == 3
    assert result["data"]["total_count"] == 3
    assert "3/3" in result["summary"]
    assert set(result.keys()) == {"intent", "data", "summary"}


# ── cross-user isolation (security) ──────────────────────────────────────────

def test_cross_user_isolation_leave_balance(monkeypatch) -> None:
    _, fn = _make_tool(monkeypatch)
    r_hr      = asyncio.run(fn(USER_HR,      "leave_balance"))
    r_finance = asyncio.run(fn(USER_FINANCE, "leave_balance"))

    # mỗi user thấy đúng data của mình
    assert r_hr["data"]["annual_remaining"] == 8
    assert r_finance["data"]["annual_remaining"] == 5
    # data không bị lẫn
    assert r_hr["data"] != r_finance["data"]


def test_cross_user_isolation_onboarding(monkeypatch) -> None:
    _, fn = _make_tool(monkeypatch)
    r_hr      = asyncio.run(fn(USER_HR,      "onboarding"))
    r_finance = asyncio.run(fn(USER_FINANCE, "onboarding"))

    assert r_hr["data"]["status"] == "completed"
    assert r_finance["data"]["status"] == "in_progress"
    assert r_hr["data"]["completed_count"] != r_finance["data"]["completed_count"]


# ── error cases ───────────────────────────────────────────────────────────────

def test_unknown_user_raises(monkeypatch) -> None:
    _, fn = _make_tool(monkeypatch)
    with pytest.raises(ValueError, match="no HR data"):
        asyncio.run(fn(USER_UNKNOWN, "leave_balance"))


def test_summary_uses_proper_vietnamese(monkeypatch) -> None:
    _, fn = _make_tool(monkeypatch)
    r_lb = asyncio.run(fn(USER_HR, "leave_balance"))
    r_at = asyncio.run(fn(USER_HR, "attendance"))
    r_ob = asyncio.run(fn(USER_HR, "onboarding"))

    # kiểm tra có dấu tiếng Việt thật sự (không phải romanized)
    assert "Bạn" in r_lb["summary"]
    assert "ngày" in r_lb["summary"]
    assert "Tháng" in r_at["summary"]
    assert "Trạng thái" in r_ob["summary"]
