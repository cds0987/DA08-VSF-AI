from __future__ import annotations

from fastapi.testclient import TestClient

import app.core.config as core_config
from app.api.routes import get_repo, get_settings
from app.core.config import HrSettings
from app.domain.entities.dtos import (
    AttendanceDTO,
    LeaveBalanceDTO,
    LeaveRequestDTO,
    OnboardingDTO,
    OnboardingItemDTO,
)
from app.domain.repositories.hr_repository import HrRepository
from app.main import app


USER_HR = "11111111-1111-4111-8111-111111111111"
USER_FINANCE = "22222222-2222-4222-8222-222222222222"


class FakeHrRepository(HrRepository):
    async def ping(self) -> None:
        return None

    async def get_leave_balance(self, user_id: str):
        data = {
            USER_HR: LeaveBalanceDTO(12, 4, 8, 10, 1, 9),
            USER_FINANCE: LeaveBalanceDTO(12, 7, 5, 10, 0, 10),
        }
        return data.get(user_id)

    async def get_leave_requests(self, user_id: str):
        data = {
            USER_HR: [
                LeaveRequestDTO("annual", "2026-06-10", "2026-06-11", 2, "approved"),
                LeaveRequestDTO("sick", "2026-06-18", "2026-06-18", 1, "pending"),
            ],
            USER_FINANCE: [
                LeaveRequestDTO("annual", "2026-06-18", "2026-06-18", 1, "pending"),
            ],
        }
        return data.get(user_id, [])

    async def get_attendance(self, user_id: str):
        data = {
            USER_HR: AttendanceDTO("2026-06", 20, 1, 0),
            USER_FINANCE: AttendanceDTO("2026-06", 19, 2, 1),
        }
        return data.get(user_id)

    async def get_onboarding(self, user_id: str):
        data = {
            USER_HR: OnboardingDTO(
                "completed",
                [
                    OnboardingItemDTO("Nhat laptop va the", True),
                    OnboardingItemDTO("Hoan thanh dao tao bao mat", True),
                    OnboardingItemDTO("Gap go team", True),
                ],
                3,
                3,
            ),
            USER_FINANCE: OnboardingDTO(
                "in_progress",
                [
                    OnboardingItemDTO("Nhat laptop va the", True),
                    OnboardingItemDTO("Hoan thanh dao tao bao mat", False),
                    OnboardingItemDTO("Gap go team", False),
                ],
                1,
                3,
            ),
        }
        return data.get(user_id)

    async def get_payroll(self, user_id: str):
        return []

    async def aclose(self) -> None:
        return None


def _client() -> TestClient:
    return TestClient(app)


def setup_module() -> None:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_repo] = lambda: FakeHrRepository()
    app.dependency_overrides[get_settings] = lambda: HrSettings(
        host="0.0.0.0",
        port=8004,
        log_level="INFO",
        database_url="",
        internal_token="",
    )
    app.dependency_overrides[core_config.get_settings] = lambda: HrSettings(
        host="0.0.0.0",
        port=8004,
        log_level="INFO",
        database_url="",
        internal_token="",
    )


def teardown_module() -> None:
    app.dependency_overrides.clear()


def test_leave_balance_endpoint() -> None:
    client = _client()
    response = client.post("/hr/query", json={"user_id": USER_HR, "intent": "leave_balance"})
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "leave_balance"
    assert body["data"]["annual_remaining"] == 8
    assert "ban con 8 ngay phep nam" in body["summary"].lower()


def test_user_isolation() -> None:
    client = _client()
    response_a = client.post("/hr/query", json={"user_id": USER_HR, "intent": "leave_balance"})
    response_b = client.post("/hr/query", json={"user_id": USER_FINANCE, "intent": "leave_balance"})
    assert response_a.json()["data"] != response_b.json()["data"]


def test_health_endpoint() -> None:
    client = _client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
