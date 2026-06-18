from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.application.exceptions import ConflictError, NotFoundError
from app.application.use_cases.users.delete_user_use_case import DeleteUserResult
from app.domain.entities.user import User, UserRole
from app.interfaces.api import dependencies
from app.interfaces.api.main import app


class FakeDeleteUserUseCase:
    async def execute(self, actor, user_id, ip_address=None):
        if user_id == "missing":
            raise NotFoundError()
        if user_id == "self":
            raise ConflictError("Cannot delete your own account")
        return DeleteUserResult(id=user_id)


async def mock_require_admin():
    return User(
        id=str(uuid4()),
        email="admin@company.com",
        role=UserRole.ADMIN,
        is_active=True,
        account_type="internal",
    )


def test_admin_can_delete_user():
    app.dependency_overrides[dependencies.require_admin] = mock_require_admin
    app.dependency_overrides[dependencies.get_delete_user_use_case] = lambda: FakeDeleteUserUseCase()

    client = TestClient(app)
    response = client.delete(f"/users/{uuid4()}")

    assert response.status_code == 204
    app.dependency_overrides.clear()


def test_delete_missing_user_returns_404():
    app.dependency_overrides[dependencies.require_admin] = mock_require_admin
    app.dependency_overrides[dependencies.get_delete_user_use_case] = lambda: FakeDeleteUserUseCase()

    client = TestClient(app)
    response = client.delete("/users/missing")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_delete_self_returns_409():
    app.dependency_overrides[dependencies.require_admin] = mock_require_admin
    app.dependency_overrides[dependencies.get_delete_user_use_case] = lambda: FakeDeleteUserUseCase()

    client = TestClient(app)
    response = client.delete("/users/self")

    assert response.status_code == 409
    app.dependency_overrides.clear()


def test_non_admin_cannot_delete_user():
    async def mock_require_admin_fail():
        raise HTTPException(status_code=403, detail="Admin only")

    app.dependency_overrides[dependencies.require_admin] = mock_require_admin_fail

    client = TestClient(app)
    response = client.delete(f"/users/{uuid4()}")

    assert response.status_code == 403
    app.dependency_overrides.clear()
