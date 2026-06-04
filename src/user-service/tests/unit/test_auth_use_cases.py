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
            department=user.department,
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


def make_user(active: bool = True) -> User:
    return User(
        id=str(uuid4()),
        email="user@company.com",
        role=UserRole.USER,
        is_active=active,
        department="HR",
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
async def test_login_rejects_inactive_user() -> None:
    use_case, _, audit = make_login_case(make_user(active=False))

    with pytest.raises(InactiveUserError):
        await use_case.execute("user@company.com", "secret")

    assert audit.actions == ["login_failed"]


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

