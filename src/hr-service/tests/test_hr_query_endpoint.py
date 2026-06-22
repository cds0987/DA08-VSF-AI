from __future__ import annotations

import datetime

from fastapi.testclient import TestClient

import app.core.config as core_config
from app.api.routes import get_repo, get_settings
from app.core.config import HrSettings
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
from app.domain.repositories.hr_repository import HrRepository
from app.main import app


USER_HR = "11111111-1111-4111-8111-111111111111"
USER_FINANCE = "22222222-2222-4222-8222-222222222222"
USER_MANAGER = "33333333-3333-4333-8333-333333333333"


def _employee(user_id: str, department: str, *, manager_user_id: str | None, full_name: str) -> EmployeeDTO:
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    return EmployeeDTO(
        id=f"emp-{user_id[:8]}",
        user_id=user_id,
        account_type="internal",
        employee_code="VSF-001",
        company_email="user@vsf.local",
        department=department,
        job_title="AI Engineer",
        manager_user_id=manager_user_id,
        employment_status="active",
        created_at=now,
        updated_at=now,
        full_name=full_name,
        phone_number="0901234567",
        date_of_birth=datetime.date(1995, 5, 20),
        hire_date=datetime.date(2024, 3, 1),
    )


class FakeHrRepository(HrRepository):
    async def ping(self) -> None:
        return None

    async def get_leave_balance(self, user_id: str):
        data = {
            USER_HR: LeaveBalanceDTO(12, 4, 8, 10, 1, 9),
            USER_FINANCE: LeaveBalanceDTO(12, 7, 5, 10, 0, 10),
        }
        return data.get(user_id)

    async def ensure_leave_balance(
        self, user_id: str, annual_total: int = 12, sick_total: int = 10
    ) -> None:
        # Fake mặc định KHÔNG provision -> giữ nguyên ngữ nghĩa 404 cho user lạ.
        return None

    async def list_employees(self, department, employment_status, limit, offset):
        return [], 0

    async def get_employee(self, employee_id):
        return None

    async def get_employee_by_user_id(self, user_id):
        data = {
            USER_HR: _employee(USER_HR, "Phong Ky thuat", manager_user_id=USER_MANAGER,
                               full_name="Nguyen Van A"),
            USER_MANAGER: _employee(USER_MANAGER, "Phong Ky thuat", manager_user_id=None,
                                    full_name="Tran Thi Manager"),
        }
        return data.get(user_id)

    async def update_employee(self, *args, **kwargs):
        return None

    async def delete_employee_by_user_id(self, user_id: str) -> bool:
        return False

    async def upsert_employee_from_user(
        self, user_id: str, email: str, department: str, is_active: bool
    ) -> None:
        return None

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
        data = {
            USER_HR: [PayrollDTO("2026-05", 1200.0, 200.0, 1000.0)],
            USER_FINANCE: [PayrollDTO("2026-05", 1500.0, 250.0, 1250.0)],
        }
        return data.get(user_id, [])

    async def get_benefits(self, user_id: str):
        data = {
            USER_HR: BenefitsDTO(
                [
                    BenefitItemDTO("Bao hiem suc khoe", "Goi A"),
                    BenefitItemDTO("Phu cap an trua", "30 USD/thang"),
                ]
            ),
        }
        return data.get(user_id)

    async def get_performance(self, user_id: str):
        data = {
            USER_HR: PerformanceReviewDTO("2026-03", "Xuat sac", [{"name": "Tuyen dung", "score": 95}], None),
        }
        return data.get(user_id)

    async def aclose(self) -> None:
        return None


def _client() -> TestClient:
    return TestClient(app)


TOKEN = "dev-secret"


def setup_module() -> None:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_repo] = lambda: FakeHrRepository()
    app.dependency_overrides[get_settings] = lambda: HrSettings(
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
    )
    app.dependency_overrides[core_config.get_settings] = lambda: HrSettings(
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
    )


def teardown_module() -> None:
    app.dependency_overrides.clear()


def test_leave_balance_endpoint() -> None:
    client = _client()
    response = client.post(
        "/hr/query",
        json={"user_id": USER_HR, "intent": "leave_balance"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "leave_balance"
    assert body["data"]["annual_remaining"] == 8
    assert set(body.keys()) == {"intent", "data", "summary"}
    assert "Bạn" in body["summary"]
    assert "ngày" in body["summary"]


def test_user_isolation() -> None:
    client = _client()
    response_a = client.post("/hr/query", json={"user_id": USER_HR, "intent": "leave_balance"}, headers={"X-Internal-Token": TOKEN})
    response_b = client.post("/hr/query", json={"user_id": USER_FINANCE, "intent": "leave_balance"}, headers={"X-Internal-Token": TOKEN})
    assert response_a.json()["data"] != response_b.json()["data"]


def test_health_endpoint() -> None:
    client = _client()
    response = client.get("/health", headers={"X-Internal-Token": TOKEN})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_wrong_token_rejected() -> None:
    client = _client()
    response = client.post(
        "/hr/query",
        json={"user_id": USER_HR, "intent": "leave_balance"},
        headers={"X-Internal-Token": "wrong"},
    )
    assert response.status_code == 401


def test_missing_token_rejected() -> None:
    client = _client()
    response = client.post("/hr/query", json={"user_id": USER_HR, "intent": "leave_balance"})
    assert response.status_code == 401


def test_unknown_user_returns_404() -> None:
    client = _client()
    response = client.post(
        "/hr/query",
        json={"user_id": "99999999-9999-4999-8999-999999999999", "intent": "leave_balance"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 404


class ProvisioningFakeHrRepository(FakeHrRepository):
    """Fake mô phỏng lazy auto-create: ensure_leave_balance tạo hồ sơ mặc định, lần
    đọc sau trả về DTO mặc định (12/10)."""

    def __init__(self) -> None:
        self._provisioned: dict[str, tuple[int, int]] = {}

    async def get_leave_balance(self, user_id: str):
        base = await super().get_leave_balance(user_id)
        if base is not None:
            return base
        if user_id in self._provisioned:
            annual, sick = self._provisioned[user_id]
            return LeaveBalanceDTO(annual, 0, annual, sick, 0, sick)
        return None

    async def ensure_leave_balance(
        self, user_id: str, annual_total: int = 12, sick_total: int = 10
    ) -> None:
        self._provisioned[user_id] = (annual_total, sick_total)


def test_leave_balance_auto_provisioned_for_new_user() -> None:
    new_user = "abcabcab-abca-4bca-8bca-abcabcabcabc"
    app.dependency_overrides[get_repo] = lambda: ProvisioningFakeHrRepository()
    try:
        client = _client()
        response = client.post(
            "/hr/query",
            json={"user_id": new_user, "intent": "leave_balance"},
            headers={"X-Internal-Token": TOKEN},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["annual_remaining"] == 12
        assert body["data"]["sick_remaining"] == 10
    finally:
        app.dependency_overrides[get_repo] = lambda: FakeHrRepository()


def test_leave_balance_404_when_auto_provision_disabled() -> None:
    new_user = "abcabcab-abca-4bca-8bca-abcabcabcabc"
    app.dependency_overrides[get_repo] = lambda: ProvisioningFakeHrRepository()
    app.dependency_overrides[get_settings] = lambda: HrSettings(
        host="0.0.0.0",
        port=8004,
        log_level="INFO",
        database_url="",
        internal_token=TOKEN,
        auto_provision_leave_balance=False,
        default_annual_leave=12,
        default_sick_leave=10,
        nats_url="nats://localhost:4222",
        nats_jetstream_enabled=False,
        user_events_enabled=False,
    )
    try:
        client = _client()
        response = client.post(
            "/hr/query",
            json={"user_id": new_user, "intent": "leave_balance"},
            headers={"X-Internal-Token": TOKEN},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides[get_repo] = lambda: FakeHrRepository()
        app.dependency_overrides[get_settings] = lambda: HrSettings(
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
        )


def test_invalid_intent_rejected() -> None:
    client = _client()
    response = client.post(
        "/hr/query",
        json={"user_id": USER_HR, "intent": "recruitment"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 422


def test_payroll_endpoint() -> None:
    client = _client()
    response = client.post(
        "/hr/query",
        json={"user_id": USER_HR, "intent": "payroll"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "payroll"
    assert body["data"]["payroll"][0]["net_salary"] == 1000.0
    assert set(body.keys()) == {"intent", "data", "summary"}


def test_benefits_endpoint() -> None:
    client = _client()
    response = client.post(
        "/hr/query",
        json={"user_id": USER_HR, "intent": "benefits"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "benefits"
    assert len(body["data"]["items"]) == 2
    assert "Bao hiem suc khoe" in body["summary"]


def test_performance_endpoint() -> None:
    client = _client()
    response = client.post(
        "/hr/query",
        json={"user_id": USER_HR, "intent": "performance"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "performance"
    assert body["data"]["rating"] == "Xuat sac"
    assert "Xuat sac" in body["summary"]


def test_sensitive_intent_no_data_returns_404() -> None:
    client = _client()
    response = client.post(
        "/hr/query",
        json={"user_id": USER_FINANCE, "intent": "benefits"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 404


def test_profile_includes_employee_identity() -> None:
    """profile gộp thêm block 'employee' (nhân thân) — phòng ban, chức danh, tên quản lý."""
    client = _client()
    response = client.post(
        "/hr/profile",
        json={"user_id": USER_HR},
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    emp = response.json()["data"]["employee"]
    assert emp is not None
    assert emp["department"] == "Phong Ky thuat"
    assert emp["job_title"] == "AI Engineer"
    assert emp["employment_status"] == "active"
    assert emp["hire_date"] == "2024-03-01"
    # manager_user_id (UUID) đã được resolve sang tên người quản lý.
    assert emp["manager_name"] == "Tran Thi Manager"
    # PII nhạy (KHÔNG expose) — không được lọt vào block employee.
    assert "phone_number" not in emp
    assert "date_of_birth" not in emp


def test_profile_employee_null_when_no_record() -> None:
    """User chưa có hồ sơ nhân thân -> employee=null (LLM nói 'chưa có thông tin', KHÔNG bịa)."""
    client = _client()
    response = client.post(
        "/hr/profile",
        json={"user_id": USER_FINANCE},
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["employee"] is None
    # Các section khác vẫn hoạt động bình thường.
    assert "leave_balance" in data
