from uuid import uuid4

import pytest

from app.application.exceptions import NotFoundError, PermissionDeniedError
from app.application.use_cases.users.list_users_use_case import ListUsersUseCase
from app.application.use_cases.users.set_user_active_use_case import SetUserActiveUseCase
from app.domain.entities.user import User, UserRole
from tests.unit.test_auth_use_cases import InMemoryAudit, InMemoryUsers


def user(role: UserRole = UserRole.USER, active: bool = True) -> User:
    return User(
        id=str(uuid4()),
        email=f"{role.value}-{uuid4()}@company.com",
        role=role,
        is_active=active,
        account_type="internal",
        department="IT",
        hashed_password="hashed:secret",
    )


@pytest.mark.asyncio
async def test_admin_can_list_filtered_users() -> None:
    admin = user(UserRole.ADMIN)
    active_user = user(active=True)
    inactive_user = user(active=False)
    repo = InMemoryUsers([admin, active_user, inactive_user])

    result = await ListUsersUseCase(repo).execute(admin, is_active=False)

    assert result.total == 1
    assert result.items == [inactive_user]


@pytest.mark.asyncio
async def test_non_admin_cannot_list_users() -> None:
    actor = user(UserRole.USER)

    with pytest.raises(PermissionDeniedError):
        await ListUsersUseCase(InMemoryUsers([actor])).execute(actor)


@pytest.mark.asyncio
async def test_admin_can_deactivate_and_audit() -> None:
    admin = user(UserRole.ADMIN)
    target = user()
    audit = InMemoryAudit()
    result = await SetUserActiveUseCase(InMemoryUsers([admin, target]), audit).execute(
        actor=admin,
        user_id=target.id,
        is_active=False,
    )

    assert result.id == target.id
    assert result.is_active is False
    assert audit.actions == ["deactivate"]


@pytest.mark.asyncio
async def test_set_active_missing_user_raises_not_found() -> None:
    admin = user(UserRole.ADMIN)

    with pytest.raises(NotFoundError):
        await SetUserActiveUseCase(InMemoryUsers([admin]), InMemoryAudit()).execute(
            actor=admin,
            user_id=str(uuid4()),
            is_active=False,
        )

