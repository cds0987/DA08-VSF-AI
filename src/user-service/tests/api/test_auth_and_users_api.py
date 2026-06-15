import os
from uuid import uuid4

from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-user-service-secret")

from app.application.exceptions import AuthenticationError, NotFoundError
from app.domain.entities.user import User, UserRole
from app.interfaces.api import dependencies
from app.interfaces.api.main import app


class FakeLoginUseCase:
    async def execute(
        self,
        email: str,
        password: str,
        ip_address: str | None = None,
        required_role: str | None = None,
    ) -> object:
        return type(
            "LoginResult",
            (),
            {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "token_type": "bearer",
            },
        )()


class FakeAdminLoginUseCase(FakeLoginUseCase):
    async def execute(
        self,
        email: str,
        password: str,
        ip_address: str | None = None,
        required_role: str | None = None,
    ) -> object:
        if required_role == "admin" and email == "user@company.com":
            raise AuthenticationError()
        return await super().execute(email, password, ip_address, required_role)


class FakeRefreshUseCase:
    async def execute(self, refresh_token: str) -> object:
        return type(
            "RefreshResult",
            (),
            {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "token_type": "bearer",
            },
        )()


class FakeListUsersUseCase:
    async def execute(
        self,
        actor: User,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> object:
        return type(
            "UserListResult",
            (),
            {
                "items": [
                    User(
                        id=str(uuid4()),
                        email="user@company.com",
                        role=UserRole.USER,
                        is_active=True,
                        account_type="external",
                        department="HR",
                    ),
                ],
                "total": 1,
            },
        )()


class FakeSetActiveUseCase:
    async def execute(
        self,
        actor: User,
        user_id: str,
        is_active: bool,
        ip_address: str | None = None,
    ) -> object:
        if user_id == "missing":
            raise NotFoundError()
        return type(
            "SetUserActiveResult",
            (),
            {"id": user_id, "is_active": is_active},
        )()


def admin_user() -> User:
    return User(
        id=str(uuid4()),
        email="admin@company.com",
        role=UserRole.ADMIN,
        is_active=True,
        account_type="internal",
        department="IT",
    )


def normal_user() -> User:
    return User(
        id=str(uuid4()),
        email="user@company.com",
        role=UserRole.USER,
        is_active=True,
        account_type="external",
        department="HR",
    )


def setup_function() -> None:
    app.dependency_overrides.clear()


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_login_returns_refresh_token() -> None:
    app.dependency_overrides[dependencies.get_login_use_case] = lambda: FakeLoginUseCase()

    response = TestClient(app).post(
        "/auth/login",
        json={"email": "user@company.com", "password": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "access-token",
        "token_type": "bearer",
    }
    assert response.cookies.get("refresh_token") == "refresh-token"


def test_admin_login_accepts_admin_and_rejects_user_generic() -> None:
    app.dependency_overrides[dependencies.get_login_use_case] = (
        lambda: FakeAdminLoginUseCase()
    )
    client = TestClient(app)

    admin_response = client.post(
        "/auth/admin/login",
        json={"email": "admin@company.com", "password": "secret"},
    )
    user_response = client.post(
        "/auth/admin/login",
        json={"email": "user@company.com", "password": "secret"},
    )

    assert admin_response.status_code == 200
    assert user_response.status_code == 401
    assert user_response.json() == {"detail": "Invalid credentials"}


def test_login_malformed_json_returns_422() -> None:
    app.dependency_overrides[dependencies.get_login_use_case] = lambda: FakeLoginUseCase()

    response = TestClient(app).post(
        "/auth/login",
        content="{bad json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_refresh_returns_rotated_refresh_token() -> None:
    app.dependency_overrides[dependencies.get_refresh_token_use_case] = (
        lambda: FakeRefreshUseCase()
    )

    response = TestClient(app).post(
        "/auth/refresh",
        cookies={"refresh_token": "old-refresh"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "new-access-token",
        "token_type": "bearer",
    }
    assert response.cookies.get("refresh_token") == "new-refresh-token"


def test_me_returns_current_user_shape() -> None:
    app.dependency_overrides[dependencies.get_current_user] = normal_user

    response = TestClient(app).get(
        "/auth/me",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json()["account_type"] == "external"
    assert set(response.json()) == {
        "id",
        "email",
        "role",
        "account_type",
        "department",
    }


def test_users_requires_admin() -> None:
    app.dependency_overrides[dependencies.get_current_user] = normal_user

    response = TestClient(app).get(
        "/users",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin only"


def test_admin_can_list_and_deactivate_user() -> None:
    app.dependency_overrides[dependencies.get_current_user] = admin_user
    app.dependency_overrides[dependencies.get_list_users_use_case] = (
        lambda: FakeListUsersUseCase()
    )
    app.dependency_overrides[dependencies.get_set_user_active_use_case] = (
        lambda: FakeSetActiveUseCase()
    )

    client = TestClient(app)
    users_response = client.get("/users?is_active=true&limit=50&offset=0")
    deactivate_response = client.patch("/users/user-1/deactivate")

    assert users_response.status_code == 200
    assert users_response.json()["total"] == 1
    assert users_response.json()["items"][0]["account_type"] == "external"
    assert deactivate_response.status_code == 200
    assert deactivate_response.json() == {"id": "user-1", "is_active": False}


def test_deactivate_missing_user_returns_404() -> None:
    app.dependency_overrides[dependencies.get_current_user] = admin_user
    app.dependency_overrides[dependencies.get_set_user_active_use_case] = (
        lambda: FakeSetActiveUseCase()
    )

    response = TestClient(app).patch("/users/missing/deactivate")

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"

