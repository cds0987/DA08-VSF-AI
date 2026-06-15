import os

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from app.main import app
from app.core.config import get_settings

def _settings():
    settings = get_settings()
    return settings

def create_token(payload: dict, secret: str | None = None):
    # Ký bằng đúng secret app đang dùng (conftest set JWT_SECRET_KEY) -> không phụ
    # thuộc giá trị hardcode, khớp với load_settings() trong require_admin_jwt.
    secret = secret or os.environ["JWT_SECRET_KEY"]
    return jwt.encode(payload, secret, algorithm="HS256")

def test_missing_token_returns_401():
    client = TestClient(app)
    response = client.get("/hr/admin/employees")
    assert response.status_code == 401

def test_invalid_signature_returns_401():
    client = TestClient(app)
    token = create_token({"role": "admin", "sub": "123"}, "wrong-secret")
    response = client.get("/hr/admin/employees", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401

def test_non_admin_role_returns_403():
    client = TestClient(app)
    token = create_token({"role": "user", "sub": "123"})
    response = client.get("/hr/admin/employees", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403

def test_internal_token_not_accepted_for_admin_jwt():
    """X-Internal-Token không được phép truy cập admin endpoints — phải dùng Bearer JWT."""
    client = TestClient(app)
    response = client.get(
        "/hr/admin/employees",
        headers={"X-Internal-Token": os.environ["JWT_SECRET_KEY"]},
    )
    # Không có Bearer token -> 401 (OAuth2 scheme không đọc X-Internal-Token)
    assert response.status_code == 401


def test_admin_role_allowed():
    # We override the repo dependency here so it doesn't fail on DB connection,
    # but we don't override the auth dependency.
    from app.api.hr_admin import get_repo
    from tests.test_hr_admin_api import FakeHrRepository
    
    app.dependency_overrides[get_repo] = lambda: FakeHrRepository()
    
    client = TestClient(app)
    token = create_token({"role": "admin", "sub": "123"})
    response = client.get("/hr/admin/employees", headers={"Authorization": f"Bearer {token}"})
    
    assert response.status_code == 200
    app.dependency_overrides.clear()
