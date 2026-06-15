"""Lazy mock data ở stage develop (APP_STAGE=develop).

Khi stage=develop: user đồng bộ chưa có hồ sơ hỏi bất kỳ intent read nào -> routes gọi
repo.provision_mock(intent, user_id) rồi đọc lại -> 200 (không 404). Khi stage=production:
provision_mock KHÔNG được gọi -> giữ 404/NO_INFO. Khoá cả 2 chiều để tránh rò mock ra prod.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import app.core.config as core_config
from app.api.routes import get_repo, get_settings
from app.core.config import HrSettings
from app.domain.entities.dtos import (
    AttendanceDTO,
    BenefitItemDTO,
    BenefitsDTO,
    LeaveRequestDTO,
    OnboardingDTO,
    OnboardingItemDTO,
    PayrollDTO,
    PerformanceReviewDTO,
)
from app.domain.repositories.hr_repository import HrRepository
from app.main import app

TOKEN = "dev-secret"
UNKNOWN_USER = "99999999-9999-4999-8999-999999999999"

# Các intent read áp lazy mock (leave_balance dùng ensure_leave_balance riêng -> không ở đây).
MOCK_INTENTS = ["attendance", "onboarding", "payroll", "benefits", "performance", "leave_requests"]


def _settings(stage: str) -> HrSettings:
    return HrSettings(
        host="0.0.0.0",
        port=8004,
        log_level="INFO",
        database_url="",
        internal_token=TOKEN,
        auto_provision_leave_balance=True,
        default_annual_leave=12,
        default_sick_leave=10,
        nats_url="nats://localhost:4222",
        nats_jetstream_enabled=False,
        user_events_enabled=False,
        app_stage=stage,
    )


class StatefulFakeRepo(HrRepository):
    """Rỗng cho mọi user tới khi provision_mock(intent, user) được gọi (mô phỏng INSERT
    idempotent của Postgres). Đếm số lần provision để khẳng định idempotent."""

    def __init__(self) -> None:
        self._seeded: set[tuple[str, str]] = set()
        self.provision_calls = 0

    async def ping(self) -> None:
        return None

    async def provision_mock(self, intent: str, user_id: str) -> None:
        self.provision_calls += 1
        self._seeded.add((intent, user_id))  # idempotent: set -> gọi lại không nhân đôi

    def _has(self, intent: str, user_id: str) -> bool:
        return (intent, user_id) in self._seeded

    async def get_leave_balance(self, user_id: str):
        return None

    async def ensure_leave_balance(self, user_id: str, annual_total: int = 12, sick_total: int = 10) -> None:
        return None

    async def list_employees(self, department, employment_status, limit, offset):
        return [], 0

    async def get_employee(self, employee_id):
        return None

    async def get_employee_by_user_id(self, user_id):
        return None

    async def update_employee(self, employee_id, code, title, manager, fields):
        return None

    async def upsert_employee_from_user(self, user_id, email, department, is_active) -> None:
        return None

    async def get_leave_requests(self, user_id: str):
        if self._has("leave_requests", user_id):
            return [LeaveRequestDTO("annual", "2026-06-10", "2026-06-10", 1, "approved")]
        return []

    async def get_attendance(self, user_id: str):
        if self._has("attendance", user_id):
            return AttendanceDTO("2026-06", 20, 1, 0)
        return None

    async def get_onboarding(self, user_id: str):
        if self._has("onboarding", user_id):
            return OnboardingDTO("completed", [OnboardingItemDTO("Gap go team", True)], 1, 1)
        return None

    async def get_payroll(self, user_id: str):
        if self._has("payroll", user_id):
            return [PayrollDTO("2026-06", 1200.0, 180.0, 1020.0)]
        return []

    async def get_benefits(self, user_id: str):
        if self._has("benefits", user_id):
            return BenefitsDTO([BenefitItemDTO("Bao hiem suc khoe", "Goi A")])
        return None

    async def get_performance(self, user_id: str):
        if self._has("performance", user_id):
            return PerformanceReviewDTO("2026-06", "Dat", [{"name": "KPI", "score": 80}], None)
        return None

    async def aclose(self) -> None:
        return None


def _bind(repo: StatefulFakeRepo, stage: str) -> None:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: _settings(stage)
    app.dependency_overrides[core_config.get_settings] = lambda: _settings(stage)


def teardown_module() -> None:
    app.dependency_overrides.clear()


def _post(intent: str, user_id: str = UNKNOWN_USER):
    return TestClient(app).post(
        "/hr/query",
        json={"user_id": user_id, "intent": intent},
        headers={"X-Internal-Token": TOKEN},
    )


def test_develop_stage_provisions_mock_for_all_read_intents():
    repo = StatefulFakeRepo()
    _bind(repo, "develop")
    for intent in MOCK_INTENTS:
        resp = _post(intent)
        assert resp.status_code == 200, f"{intent} should 200 in develop, got {resp.status_code}"
        assert resp.json()["intent"] == intent


def test_production_stage_keeps_404_no_mock():
    repo = StatefulFakeRepo()
    _bind(repo, "production")
    # 404 cho các intent dùng HTTPException khi rỗng.
    for intent in ["attendance", "onboarding", "payroll", "benefits", "performance"]:
        resp = _post(intent)
        assert resp.status_code == 404, f"{intent} should 404 in production"
    # leave_requests trả list rỗng + summary thân thiện (200) — nhưng KHÔNG có mock.
    resp = _post("leave_requests")
    assert resp.status_code == 200
    assert resp.json()["data"]["requests"] == []
    assert repo.provision_calls == 0  # production tuyệt đối không sinh mock


def test_provision_idempotent_and_default_stage_is_production():
    # Default (thiếu app_stage) = production -> không mock.
    assert _settings("production").is_develop is False
    assert _settings("develop").is_develop is True
    repo = StatefulFakeRepo()
    _bind(repo, "develop")
    _post("payroll")
    _post("payroll")  # gọi lại cùng user/intent
    assert len([k for k in repo._seeded if k[0] == "payroll"]) == 1  # idempotent
