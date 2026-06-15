import pytest
from uuid import uuid4
from app.application.exceptions import ConflictError, PermissionDeniedError
from app.application.use_cases.users.create_user_use_case import CreateUserUseCase
from app.domain.entities.user import User, UserRole
from tests.unit.test_auth_use_cases import FakePasswordHasher, InMemoryUsers

class InMemoryEventEmitter:
    def __init__(self):
        self.emitted = []

    async def emit(self, subject: str, user: User) -> None:
        self.emitted.append((subject, user))

def user(role: UserRole = UserRole.USER, active: bool = True, email: str | None = None) -> User:
    return User(
        id=str(uuid4()),
        email=email or f"{role.value}-{uuid4()}@company.com",
        role=role,
        is_active=active,
        account_type="internal",
        hashed_password="hashed:secret",
    )

@pytest.mark.asyncio
async def test_admin_can_create_user() -> None:
    admin = user(UserRole.ADMIN)
    repo = InMemoryUsers([admin])
    hasher = FakePasswordHasher()
    emitter = InMemoryEventEmitter()
    use_case = CreateUserUseCase(repo, hasher, emitter)

    created = await use_case.execute(
        actor=admin,
        email="new@company.com",
        password="password123",
        role="user",
        account_type="internal",
    )

    assert created.email == "new@company.com"
    assert created.hashed_password == "hashed:password123"
    assert created.role == "user"
    assert created.is_active is True

    # Check repository
    assert await repo.get_by_email("new@company.com") == created

    # Check event
    assert len(emitter.emitted) == 1
    assert emitter.emitted[0][0] == "user.created"
    assert emitter.emitted[0][1] == created

@pytest.mark.asyncio
async def test_non_admin_cannot_create_user() -> None:
    actor = user(UserRole.USER)
    repo = InMemoryUsers([actor])
    hasher = FakePasswordHasher()
    use_case = CreateUserUseCase(repo, hasher)

    with pytest.raises(PermissionDeniedError):
        await use_case.execute(
            actor=actor,
            email="new@company.com",
            password="password123",
            role="user",
            account_type="internal",
        )

@pytest.mark.asyncio
async def test_create_user_with_duplicate_email_raises_conflict() -> None:
    from sqlalchemy.exc import IntegrityError

    class FakeDuplicateRepo:
        async def create(self, user: User) -> User:
            raise IntegrityError("duplicate key value violates unique constraint", params={}, orig=Exception())
        async def get_by_email(self, email: str) -> User | None:
            return None

    admin = user(UserRole.ADMIN)
    repo = FakeDuplicateRepo()
    hasher = FakePasswordHasher()
    use_case = CreateUserUseCase(repo, hasher)

    with pytest.raises(ConflictError):
        await use_case.execute(
            actor=admin,
            email="existing@company.com",
            password="password123",
            role="user",
            account_type="internal",
        )

def test_role_value_helper():
    from app.application.use_cases.users.create_user_use_case import _role_value
    assert _role_value(UserRole.ADMIN) == "admin"
    assert _role_value("admin") == "admin"


@pytest.mark.asyncio
async def test_repo_fail_does_not_emit_event() -> None:
    """Khi repository.create ném exception không phải IntegrityError,
    event KHÔNG được emit."""
    class FailingRepo:
        async def create(self, u: User) -> User:
            raise RuntimeError("db down")
        async def get_by_email(self, email: str) -> User | None:
            return None

    admin = user(UserRole.ADMIN)
    emitter = InMemoryEventEmitter()
    use_case = CreateUserUseCase(FailingRepo(), FakePasswordHasher(), emitter)

    with pytest.raises(RuntimeError, match="db down"):
        await use_case.execute(
            actor=admin,
            email="new@company.com",
            password="pass1234",
            role="user",
            account_type="internal",
        )

    assert emitter.emitted == [], "event không được emit khi repo fail"


def test_event_payload_does_not_contain_password() -> None:
    """user_to_payload (dùng bởi NatsUserEventEmitter) không được chứa
    hashed_password hay bất kỳ dữ liệu liên quan password."""
    from app.infrastructure.messaging.user_event_emitter import user_to_payload
    from app.domain.entities.user import User as UserEntity

    u = UserEntity(
        id="test-id",
        email="emp@company.com",
        role=UserRole.USER,
        is_active=True,
        account_type="internal",
        hashed_password="bcrypt:$2b$12$verysecret",
    )
    payload = user_to_payload(u)

    forbidden_keys = {"password", "hashed_password", "hash"}
    for key in payload:
        assert key.lower() not in forbidden_keys, f"payload không được có key '{key}'"
    for v in payload.values():
        if isinstance(v, str):
            assert "bcrypt" not in v and "verysecret" not in v, \
                "payload không được chứa giá trị hash password"
