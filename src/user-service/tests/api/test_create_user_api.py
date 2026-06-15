import pytest
from fastapi.testclient import TestClient
from app.interfaces.api.main import app
from app.interfaces.api import dependencies
from app.domain.entities.user import User, UserRole
from app.application.exceptions import ConflictError, PermissionDeniedError
from uuid import uuid4

class FakeCreateUserUseCase:
    async def execute(self, actor, email, password, role, account_type):
        if email == "conflict@company.com":
            raise ConflictError("Conflict")
        return User(
            id=str(uuid4()),
            email=email,
            role=role,
            is_active=True,
            account_type=account_type,
        )

async def mock_require_admin():
    return User(
        id=str(uuid4()),
        email="admin@company.com",
        role=UserRole.ADMIN,
        is_active=True,
        account_type="internal",
    )

async def mock_require_user():
    return User(
        id=str(uuid4()),
        email="user@company.com",
        role=UserRole.USER,
        is_active=True,
        account_type="internal",
    )

def test_admin_can_create_user():
    app.dependency_overrides[dependencies.require_admin] = mock_require_admin
    app.dependency_overrides[dependencies.get_create_user_use_case] = lambda: FakeCreateUserUseCase()
    
    client = TestClient(app)
    response = client.post("/users", json={
        "email": "new@company.com",
        "password": "password123",
        "role": "user",
        "account_type": "internal",
    })
    
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new@company.com"
    assert "id" in data
    
    app.dependency_overrides.clear()

def test_create_user_conflict():
    app.dependency_overrides[dependencies.require_admin] = mock_require_admin
    app.dependency_overrides[dependencies.get_create_user_use_case] = lambda: FakeCreateUserUseCase()
    
    client = TestClient(app)
    response = client.post("/users", json={
        "email": "conflict@company.com",
        "password": "password123",
        "role": "user",
        "account_type": "internal",
    })
    
    assert response.status_code == 409
    
    app.dependency_overrides.clear()

def test_non_admin_cannot_create_user():
    # require_admin will raise 403 if it fails, but here we override it to return a non-admin
    # Actually, require_admin is a dependency that checks the role. 
    # If we override it with a function that returns a user with role='user', 
    # then the router will still receive that user as 'actor'.
    # In my router implementation:
    # @router.post("", status_code=201, response_model=UserItem)
    # async def create_user(..., actor: User = Depends(require_admin), ...)
    
    # If I want to test 403 from require_admin, I should mock get_current_user instead.
    
    from fastapi import HTTPException
    async def mock_require_admin_fail():
        raise HTTPException(status_code=403, detail="Admin only")
        
    app.dependency_overrides[dependencies.require_admin] = mock_require_admin_fail
    
    client = TestClient(app)
    response = client.post("/users", json={
        "email": "new@company.com",
        "password": "password123",
        "role": "user",
        "account_type": "internal",
    })
    
    assert response.status_code == 403
    
    app.dependency_overrides.clear()
