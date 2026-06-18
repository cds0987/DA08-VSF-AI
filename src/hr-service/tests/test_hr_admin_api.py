import pytest
import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.api.hr_admin import get_repo, get_publisher
from app.api.auth import require_admin_jwt
from app.domain.entities.dtos import EmployeeDTO
from app.domain.repositories.hr_repository import HrRepository
from jose import jwt

class FakeHrRepository(HrRepository):
    def __init__(self):
        self.employees = [
            EmployeeDTO(
                id="emp-1",
                user_id="user-1",
                account_type="internal",
                employee_code="EMP-001",
                company_email="emp1@company.com",
                department="Engineering",
                job_title="Dev",
                manager_user_id=None,
                employment_status="active",
                created_at=datetime.datetime.now(datetime.timezone.utc),
                updated_at=datetime.datetime.now(datetime.timezone.utc),
            )
        ]

    async def ping(self) -> None: return None
    async def get_leave_balance(self, user_id): return None
    async def ensure_leave_balance(self, user_id, a, s): return None
    async def upsert_employee_from_user(self, u, e, d, i, acc_type="internal"): return None
    async def get_leave_requests(self, u): return []
    async def get_attendance(self, u): return None
    async def get_onboarding(self, u): return None
    async def get_payroll(self, u): return []
    async def get_benefits(self, u): return None
    async def get_performance(self, u): return None
    async def aclose(self): pass

    async def delete_employee_by_user_id(self, user_id):
        before = len(self.employees)
        self.employees = [e for e in self.employees if e.user_id != user_id]
        return len(self.employees) < before

    async def list_employees(self, department, employment_status, limit, offset):
        return self.employees, len(self.employees)

    async def get_employee(self, employee_id):
        for e in self.employees:
            if e.id == employee_id:
                return e
        return None

    async def get_employee_by_user_id(self, user_id):
        for e in self.employees:
            if e.user_id == user_id:
                return e
        return None

    async def update_employee(self, employee_id, employee_code, job_title, manager_user_id,
                              full_name=None, phone_number=None, date_of_birth=None,
                              hire_date=None, department=None, provided_fields=frozenset()):
        for i, e in enumerate(self.employees):
            if e.id == employee_id:
                updated = EmployeeDTO(
                    id=e.id,
                    user_id=e.user_id,
                    account_type=e.account_type,
                    employee_code=employee_code if "employee_code" in provided_fields else e.employee_code,
                    company_email=e.company_email,
                    department=department if "department" in provided_fields else e.department,
                    job_title=job_title if "job_title" in provided_fields else e.job_title,
                    manager_user_id=manager_user_id if "manager_user_id" in provided_fields else e.manager_user_id,
                    employment_status=e.employment_status,
                    created_at=e.created_at,
                    updated_at=datetime.datetime.now(datetime.timezone.utc),
                    full_name=full_name if "full_name" in provided_fields else e.full_name,
                    phone_number=phone_number if "phone_number" in provided_fields else e.phone_number,
                    date_of_birth=date_of_birth if "date_of_birth" in provided_fields else e.date_of_birth,
                    hire_date=hire_date if "hire_date" in provided_fields else e.hire_date,
                )
                self.employees[i] = updated
                return updated
        return None

class FakePublisher:
    def __init__(self):
        self.published = []
    async def publish(self, subject, payload):
        self.published.append((subject, payload))

async def mock_require_admin_jwt():
    return {"sub": "admin-id", "role": "admin"}

def test_list_employees():
    fake_repo = FakeHrRepository()
    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: fake_repo
    
    client = TestClient(app)
    response = client.get("/hr/admin/employees")
    
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["employee_code"] == "EMP-001"
    
    app.dependency_overrides.clear()

def test_get_employee():
    fake_repo = FakeHrRepository()
    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: fake_repo
    
    client = TestClient(app)
    response = client.get("/hr/admin/employees/emp-1")
    
    assert response.status_code == 200
    assert response.json()["id"] == "emp-1"
    
    app.dependency_overrides.clear()

def test_get_employee_not_found():
    fake_repo = FakeHrRepository()
    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: fake_repo
    
    client = TestClient(app)
    response = client.get("/hr/admin/employees/missing")
    
    assert response.status_code == 404
    
    app.dependency_overrides.clear()

def test_patch_employee():
    fake_repo = FakeHrRepository()
    fake_publisher = FakePublisher()
    
    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: fake_repo
    app.dependency_overrides[get_publisher] = lambda: fake_publisher
    
    client = TestClient(app)
    response = client.patch("/hr/admin/employees/emp-1", json={
        "job_title": "Senior Dev"
    })
    
    assert response.status_code == 200
    assert response.json()["job_title"] == "Senior Dev"
    
    # Check if event was published
    assert len(fake_publisher.published) == 1
    assert fake_publisher.published[0][0] == "hr.employee_profile.updated"
    assert fake_publisher.published[0][1]["user_id"] == "user-1"
    
    app.dependency_overrides.clear()

def test_patch_employee_self_manager():
    fake_repo = FakeHrRepository()
    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: fake_repo

    client = TestClient(app)
    response = client.patch("/hr/admin/employees/emp-1", json={
        "manager_user_id": "user-1"
    })

    assert response.status_code == 400
    assert "cannot be their own manager" in response.json()["detail"]

    app.dependency_overrides.clear()


def test_patch_empty_body_returns_422():
    """Request body rỗng (không có field nào) phải bị reject 422."""
    fake_repo = FakeHrRepository()
    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: fake_repo

    client = TestClient(app)
    response = client.patch("/hr/admin/employees/emp-1", json={})

    assert response.status_code == 422

    app.dependency_overrides.clear()


def test_patch_empty_string_normalized_to_null():
    """String rỗng/khoảng trắng trong employee_code, job_title được normalize thành null."""
    fake_repo = FakeHrRepository()
    fake_publisher = FakePublisher()
    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: fake_repo
    app.dependency_overrides[get_publisher] = lambda: fake_publisher

    client = TestClient(app)
    response = client.patch("/hr/admin/employees/emp-1", json={
        "job_title": "   "
    })

    assert response.status_code == 200
    assert response.json()["job_title"] is None

    app.dependency_overrides.clear()


def test_patch_duplicate_employee_code_returns_409():
    """Duplicate employee_code phải trả 409."""
    class ConflictRepo(FakeHrRepository):
        async def update_employee(self, *args, **kwargs):
            raise ValueError("Duplicate employee_code")

    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: ConflictRepo()

    client = TestClient(app)
    response = client.patch("/hr/admin/employees/emp-1", json={
        "employee_code": "EMP-001"
    })

    assert response.status_code == 409

    app.dependency_overrides.clear()


def test_patch_manager_not_found_returns_404():
    """manager_user_id không tồn tại trong DB phải bị reject."""
    class NoManagerRepo(FakeHrRepository):
        async def get_employee_by_user_id(self, user_id):
            return None  # manager không tồn tại

    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: NoManagerRepo()

    client = TestClient(app)
    response = client.patch("/hr/admin/employees/emp-1", json={
        "manager_user_id": "nonexistent-user"
    })

    # Use case raise ValueError("Manager not found") → router map "not found" → 404
    assert response.status_code == 404
    assert "manager" in response.json()["detail"].lower()

    app.dependency_overrides.clear()


def test_patch_db_fail_no_event_published():
    """Khi DB update fail, event hr.employee_profile.updated không được publish."""
    class FailingUpdateRepo(FakeHrRepository):
        async def update_employee(self, *args, **kwargs):
            raise RuntimeError("db write failed")

    fake_publisher = FakePublisher()
    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: FailingUpdateRepo()
    app.dependency_overrides[get_publisher] = lambda: fake_publisher

    # raise_server_exceptions=False: nhận 5xx response thay vì re-raise exception
    client = TestClient(app, raise_server_exceptions=False)
    response = client.patch("/hr/admin/employees/emp-1", json={"job_title": "X"})

    assert response.status_code == 500
    assert fake_publisher.published == [], "event không được publish khi DB fail"

    app.dependency_overrides.clear()


def test_list_employees_filter_by_department():
    """Filter department được truyền xuống repo đúng."""
    class FilterCapturingRepo(FakeHrRepository):
        def __init__(self):
            super().__init__()
            self.called_with = {}

        async def list_employees(self, department, employment_status, limit, offset):
            self.called_with = {
                "department": department,
                "employment_status": employment_status,
                "limit": limit,
                "offset": offset,
            }
            return [], 0

    repo = FilterCapturingRepo()
    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: repo

    client = TestClient(app)
    response = client.get("/hr/admin/employees?department=Engineering&status=active&limit=10&offset=5")

    assert response.status_code == 200
    assert repo.called_with["department"] == "Engineering"
    assert repo.called_with["employment_status"] == "active"
    assert repo.called_with["limit"] == 10
    assert repo.called_with["offset"] == 5

    app.dependency_overrides.clear()


def test_delete_employee_removes_profile():
    """DELETE /hr/admin/employees/{id} xóa HR profile và trả 204."""
    fake_repo = FakeHrRepository()
    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: fake_repo

    client = TestClient(app)
    response = client.delete("/hr/admin/employees/emp-1")

    assert response.status_code == 204
    assert fake_repo.employees == []

    app.dependency_overrides.clear()


def test_delete_employee_not_found_returns_404():
    """DELETE /hr/admin/employees/{id} trả 404 khi không tìm thấy profile."""
    fake_repo = FakeHrRepository()
    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: fake_repo

    client = TestClient(app)
    response = client.delete("/hr/admin/employees/nonexistent")

    assert response.status_code == 404

    app.dependency_overrides.clear()


def test_list_employees_total_reflects_filter():
    """total trong response phản ánh số bản ghi sau filter, không phải sau limit."""
    class TotalRepo(FakeHrRepository):
        async def list_employees(self, department, employment_status, limit, offset):
            # Giả lập: 50 bản ghi thoả filter nhưng chỉ trả limit=2
            return self.employees[:1], 50

    app.dependency_overrides[require_admin_jwt] = mock_require_admin_jwt
    app.dependency_overrides[get_repo] = lambda: TotalRepo()

    client = TestClient(app)
    response = client.get("/hr/admin/employees?limit=1")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 50
    assert len(data["items"]) == 1

    app.dependency_overrides.clear()
