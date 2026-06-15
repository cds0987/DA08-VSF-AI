from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.application.exceptions import (
    AccountLockedError,
    AuthenticationError,
    InactiveUserError,
    InvalidTokenError,
)
from app.application.security import AccessToken
from app.application.use_cases.auth.login_use_case import (
    LoginSecurityState,
    LoginUseCase,
)
from app.application.use_cases.auth.refresh_token_use_case import (
    RefreshTokenRecord,
    RefreshTokenUseCase,
)
from app.domain.entities.user import User, UserRole
from app.infrastructure.security.refresh_token_issuer import RefreshTokenIssuer


class FakePasswordHasher:
    def hash(self, plain_text: str) -> str:
        return f"hashed:{plain_text}"

    def verify(self, plain_text: str, hashed: str) -> bool:
        return hashed == self.hash(plain_text)


class FakeTokenService:
    def create_access_token(self, user: User) -> AccessToken:
        return AccessToken(
            token=f"access:{user.id}",
            jti="jti-1",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

    def decode_access_token(self, token: str) -> dict:
        if not token.startswith("access:"):
            raise ValueError("bad token")
        return {"sub": token.removeprefix("access:"), "jti": "jti-1"}


class InMemoryUsers:
    def __init__(self, users: list[User]) -> None:
        self.users = {user.id: user for user in users}

    async def get_by_email(self, email: str) -> User | None:
        return next((user for user in self.users.values() if user.email == email), None)

    async def get_by_id(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    async def create(self, user: User) -> User:
        self.users[user.id] = user
        return user

    async def list_all(
        self,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        users = list(self.users.values())
        if is_active is not None:
            users = [user for user in users if user.is_active is is_active]
        return users[offset : offset + limit], len(users)

    async def set_active(self, user_id: str, is_active: bool) -> User | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        updated = User(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=is_active,
            account_type=user.account_type,
            hashed_password=user.hashed_password,
            auth_provider=user.auth_provider,
        )
        self.users[user_id] = updated
        return updated


class InMemoryLoginState:
    def __init__(self) -> None:
        self.states: dict[str, LoginSecurityState] = {}

    async def get_login_state(self, user_id: str) -> LoginSecurityState:
        return self.states.get(user_id, LoginSecurityState(0, None))

    async def register_login_failure(
        self,
        user_id: str,
        failed_login_count: int,
        locked_until: datetime | None,
    ) -> None:
        self.states[user_id] = LoginSecurityState(failed_login_count, locked_until)

    async def reset_login_failures(self, user_id: str) -> None:
        self.states[user_id] = LoginSecurityState(0, None)


class InMemoryAudit:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def log(self, action: str, **kwargs: object) -> None:
        self.actions.append(action)


class InMemoryRefreshTokens:
    def __init__(self) -> None:
        self.records: dict[str, RefreshTokenRecord] = {}

    async def create(
        self,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        self.records[token_id] = RefreshTokenRecord(
            id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

    async def get_by_id(self, token_id: str) -> RefreshTokenRecord | None:
        return self.records.get(token_id)

    async def revoke(self, token_id: str) -> None:
        record = self.records[token_id]
        self.records[token_id] = RefreshTokenRecord(
            id=record.id,
            user_id=record.user_id,
            token_hash=record.token_hash,
            expires_at=record.expires_at,
            revoked_at=datetime.now(timezone.utc),
        )


class MissingUserResult:
    def scalar_one_or_none(self) -> object | None:
        return None


class MissingUserSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def execute(self, statement: object) -> MissingUserResult:
        return MissingUserResult()

    async def commit(self) -> None:
        self.commit_count += 1


class NonRaisingFailedPasswordLoginUseCase(LoginUseCase):
    async def _handle_failed_password(self, user: User, ip_address: str | None) -> None:
        return None


def make_user(active: bool = True) -> User:
    return User(
        id=str(uuid4()),
        email="user@company.com",
        role=UserRole.USER,
        is_active=active,
        account_type="internal",
        hashed_password="hashed:secret",
    )


def make_login_case(user: User) -> tuple[LoginUseCase, InMemoryLoginState, InMemoryAudit]:
    hasher = FakePasswordHasher()
    refresh_store = InMemoryRefreshTokens()
    state = InMemoryLoginState()
    audit = InMemoryAudit()
    use_case = LoginUseCase(
        user_repository=InMemoryUsers([user]),
        password_hasher=hasher,
        token_service=FakeTokenService(),
        refresh_token_issuer=RefreshTokenIssuer(refresh_store, hasher),
        login_state_repository=state,
        audit_logger=audit,
        failed_login_threshold=2,
        lockout_minutes=15,
    )
    return use_case, state, audit


@pytest.mark.asyncio
async def test_login_success_issues_access_and_refresh_token() -> None:
    user = make_user()
    use_case, state, audit = make_login_case(user)

    result = await use_case.execute("user@company.com", "secret")

    assert result.access_token == f"access:{user.id}"
    assert result.refresh_token.count(".") == 1
    assert (await state.get_login_state(user.id)).failed_login_count == 0
    assert audit.actions == ["login"]


@pytest.mark.asyncio
async def test_login_required_admin_role_rejects_normal_user() -> None:
    user = make_user()
    use_case, _, audit = make_login_case(user)

    with pytest.raises(AuthenticationError):
        await use_case.execute("user@company.com", "secret", required_role="admin")

    assert audit.actions == ["login_failed"]


@pytest.mark.asyncio
async def test_login_failure_increments_count_and_locks() -> None:
    user = make_user()
    use_case, state, audit = make_login_case(user)

    with pytest.raises(AuthenticationError):
        await use_case.execute("user@company.com", "wrong")
    with pytest.raises(AccountLockedError):
        await use_case.execute("user@company.com", "wrong")

    locked_state = await state.get_login_state(user.id)
    assert locked_state.failed_login_count == 2
    assert locked_state.locked_until is not None
    assert audit.actions == ["login_failed", "account_locked"]


@pytest.mark.asyncio
async def test_login_wrong_password_fails_even_if_helper_does_not_raise() -> None:
    user = make_user()
    hasher = FakePasswordHasher()
    use_case = NonRaisingFailedPasswordLoginUseCase(
        user_repository=InMemoryUsers([user]),
        password_hasher=hasher,
        token_service=FakeTokenService(),
        refresh_token_issuer=RefreshTokenIssuer(InMemoryRefreshTokens(), hasher),
        login_state_repository=InMemoryLoginState(),
        audit_logger=InMemoryAudit(),
    )

    with pytest.raises(AuthenticationError):
        await use_case.execute("user@company.com", "wrong")


@pytest.mark.asyncio
async def test_login_rejects_inactive_user() -> None:
    use_case, _, audit = make_login_case(make_user(active=False))

    with pytest.raises(InactiveUserError):
        await use_case.execute("user@company.com", "secret")

    assert audit.actions == ["login_failed"]


def test_settings_rejects_weak_jwt_secret() -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(jwt_secret_key="change-me-in-env")


def test_access_token_default_ttl_is_15_minutes() -> None:
    from app.core.config import Settings
    from app.infrastructure.security.jwt_token_service import JwtTokenService

    settings = Settings(jwt_secret_key="strong-test-secret")
    token_service = JwtTokenService(secret_key="strong-test-secret")

    assert settings.access_token_ttl_minutes == 15
    assert token_service.ttl_minutes == 15


def test_jwt_payload_includes_account_type() -> None:
    from jose import jwt

    from app.infrastructure.security.jwt_token_service import JwtTokenService

    secret = "strong-test-secret"
    user = make_user()
    token_service = JwtTokenService(secret_key=secret)

    access_token = token_service.create_access_token(user)
    payload = jwt.decode(access_token.token, secret, algorithms=["HS256"])

    assert payload["sub"] == user.id
    assert payload["user_id"] == user.id
    assert payload["role"] == "user"
    assert payload["account_type"] == "internal"
    assert "department" not in payload
    assert payload["jti"] == access_token.jti


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_rejects_old_one() -> None:
    user = make_user()
    users = InMemoryUsers([user])
    hasher = FakePasswordHasher()
    refresh_store = InMemoryRefreshTokens()
    issuer = RefreshTokenIssuer(refresh_store, hasher)
    old_refresh = await issuer.issue(user.id)

    use_case = RefreshTokenUseCase(
        user_repository=users,
        refresh_token_repository=refresh_store,
        refresh_token_issuer=issuer,
        password_hasher=hasher,
        token_service=FakeTokenService(),
    )

    result = await use_case.execute(old_refresh)

    assert result.access_token == f"access:{user.id}"
    assert result.refresh_token != old_refresh
    with pytest.raises(InvalidTokenError):
        await use_case.execute(old_refresh)


@pytest.mark.asyncio
async def test_refresh_access_token_preserves_document_acl_claims() -> None:
    from jose import jwt

    from app.infrastructure.security.jwt_token_service import JwtTokenService

    secret = "strong-test-secret"
    user = User(
        id=str(uuid4()),
        email="external@company.com",
        role=UserRole.USER,
        is_active=True,
        account_type="external",
        hashed_password="hashed:secret",
    )
    users = InMemoryUsers([user])
    hasher = FakePasswordHasher()
    refresh_store = InMemoryRefreshTokens()
    issuer = RefreshTokenIssuer(refresh_store, hasher)
    refresh_token = await issuer.issue(user.id)
    token_service = JwtTokenService(secret_key=secret)
    use_case = RefreshTokenUseCase(
        user_repository=users,
        refresh_token_repository=refresh_store,
        refresh_token_issuer=issuer,
        password_hasher=hasher,
        token_service=token_service,
    )

    result = await use_case.execute(refresh_token)
    payload = jwt.decode(result.access_token, secret, algorithms=["HS256"])

    assert payload["sub"] == user.id
    assert payload["role"] == "user"
    assert payload["account_type"] == "external"
    assert "department" not in payload


@pytest.mark.asyncio
async def test_refresh_rejects_malformed_token_id() -> None:
    user = make_user()
    hasher = FakePasswordHasher()
    use_case = RefreshTokenUseCase(
        user_repository=InMemoryUsers([user]),
        refresh_token_repository=InMemoryRefreshTokens(),
        refresh_token_issuer=RefreshTokenIssuer(InMemoryRefreshTokens(), hasher),
        password_hasher=hasher,
        token_service=FakeTokenService(),
    )

    with pytest.raises(InvalidTokenError):
        await use_case.execute("not-a-uuid.secret")


@pytest.mark.asyncio
async def test_login_state_repository_handles_missing_user_gracefully() -> None:
    from app.infrastructure.db.postgres_user_repository import PostgresLoginStateRepository

    session = MissingUserSession()
    repository = PostgresLoginStateRepository(session)  # type: ignore[arg-type]

    await repository.register_login_failure(str(uuid4()), 1, None)
    await repository.reset_login_failures(str(uuid4()))

    assert session.commit_count == 0

