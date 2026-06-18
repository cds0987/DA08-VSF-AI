from uuid import uuid4

import pytest

from app.application.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.application.use_cases.users.delete_user_use_case import DeleteUserUseCase
from app.domain.entities.user import User, UserRole
from tests.unit.test_auth_use_cases import InMemoryAudit, InMemoryUsers
from tests.unit.test_create_user_use_case import InMemoryEventEmitter


def user(role: UserRole = UserRole.USER, active: bool = True) -> User:
    return User(
        id=str(uuid4()),
        email=f"{role.value}-{uuid4()}@company.com",
        role=role,
        is_active=active,
        account_type="internal",
        hashed_password="hashed:secret",
    )


@pytest.mark.asyncio
async def test_admin_can_delete_user_and_emits_event() -> None:
    admin = user(UserRole.ADMIN)
    target = user()
    repo = InMemoryUsers([admin, target])
    audit = InMemoryAudit()
    emitter = InMemoryEventEmitter()

    result = await DeleteUserUseCase(repo, audit, emitter).execute(
        actor=admin, user_id=target.id
    )

    assert result.id == target.id
    assert await repo.get_by_id(target.id) is None
    assert audit.actions == ["delete"]
    assert len(emitter.emitted) == 1
    assert emitter.emitted[0][0] == "user.deleted"
    assert emitter.emitted[0][1].id == target.id


@pytest.mark.asyncio
async def test_non_admin_cannot_delete_user() -> None:
    actor = user(UserRole.USER)
    target = user()
    repo = InMemoryUsers([actor, target])

    with pytest.raises(PermissionDeniedError):
        await DeleteUserUseCase(repo, InMemoryAudit()).execute(
            actor=actor, user_id=target.id
        )
    assert await repo.get_by_id(target.id) is not None


@pytest.mark.asyncio
async def test_delete_missing_user_raises_not_found() -> None:
    admin = user(UserRole.ADMIN)
    repo = InMemoryUsers([admin])

    with pytest.raises(NotFoundError):
        await DeleteUserUseCase(repo, InMemoryAudit()).execute(
            actor=admin, user_id=str(uuid4())
        )


@pytest.mark.asyncio
async def test_admin_cannot_delete_self() -> None:
    admin = user(UserRole.ADMIN)
    repo = InMemoryUsers([admin])
    emitter = InMemoryEventEmitter()

    with pytest.raises(ConflictError):
        await DeleteUserUseCase(repo, InMemoryAudit(), emitter).execute(
            actor=admin, user_id=admin.id
        )
    assert await repo.get_by_id(admin.id) is not None
    assert emitter.emitted == []


@pytest.mark.asyncio
async def test_delete_failure_does_not_emit_event() -> None:
    """Nếu repository.delete trả False (race/không tồn tại) thì không emit event."""

    class FlakyRepo(InMemoryUsers):
        async def delete(self, user_id: str) -> bool:
            return False

    admin = user(UserRole.ADMIN)
    target = user()
    repo = FlakyRepo([admin, target])
    emitter = InMemoryEventEmitter()

    with pytest.raises(NotFoundError):
        await DeleteUserUseCase(repo, InMemoryAudit(), emitter).execute(
            actor=admin, user_id=target.id
        )
    assert emitter.emitted == []
