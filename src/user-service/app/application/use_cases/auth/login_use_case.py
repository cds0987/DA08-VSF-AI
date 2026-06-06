from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from app.application.exceptions import (
    AccountLockedError,
    AuthenticationError,
    InactiveUserError,
)
from app.application.security import PasswordHasher, TokenService
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@dataclass(frozen=True)
class LoginSecurityState:
    failed_login_count: int
    locked_until: Optional[datetime]


class LoginStateRepository(Protocol):
    async def get_login_state(self, user_id: str) -> LoginSecurityState:
        ...

    async def register_login_failure(
        self,
        user_id: str,
        failed_login_count: int,
        locked_until: Optional[datetime],
    ) -> None:
        ...

    async def reset_login_failures(self, user_id: str) -> None:
        ...


class RefreshTokenIssuer(Protocol):
    async def issue(self, user_id: str) -> str:
        ...


class AuditLogger(Protocol):
    async def log(
        self,
        action: str,
        actor_id: str,
        actor_role: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        detail: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        ...


class LoginUseCase:
    def __init__(
        self,
        user_repository: UserRepository,
        password_hasher: PasswordHasher,
        token_service: TokenService,
        refresh_token_issuer: RefreshTokenIssuer,
        login_state_repository: LoginStateRepository,
        audit_logger: AuditLogger,
        failed_login_threshold: int = 5,
        lockout_minutes: int = 15,
    ) -> None:
        self.user_repository = user_repository
        self.password_hasher = password_hasher
        self.token_service = token_service
        self.refresh_token_issuer = refresh_token_issuer
        self.login_state_repository = login_state_repository
        self.audit_logger = audit_logger
        self.failed_login_threshold = failed_login_threshold
        self.lockout_minutes = lockout_minutes

    async def execute(
        self,
        email: str,
        password: str,
        ip_address: str | None = None,
    ) -> LoginResult:
        user = await self.user_repository.get_by_email(email)
        if user is None:
            raise AuthenticationError()

        await self._reject_if_locked(user, ip_address)
        if not user.is_active:
            await self._log(user, "login_failed", {"reason": "inactive"}, ip_address)
            raise InactiveUserError()

        if not user.hashed_password or not self.password_hasher.verify(
            password,
            user.hashed_password,
        ):
            await self._handle_failed_password(user, ip_address)
            raise AuthenticationError()

        await self.login_state_repository.reset_login_failures(user.id)
        access_token = self.token_service.create_access_token(user)
        refresh_token = await self.refresh_token_issuer.issue(user.id)
        await self._log(user, "login", {"jti": access_token.jti}, ip_address)
        return LoginResult(
            access_token=access_token.token,
            refresh_token=refresh_token,
        )

    async def _reject_if_locked(
        self,
        user: User,
        ip_address: str | None,
    ) -> None:
        state = await self.login_state_repository.get_login_state(user.id)
        now = datetime.now(timezone.utc)
        if state.locked_until and state.locked_until > now:
            await self._log(
                user,
                "account_locked",
                {"locked_until": state.locked_until.isoformat()},
                ip_address,
            )
            raise AccountLockedError()

    async def _handle_failed_password(
        self,
        user: User,
        ip_address: str | None,
    ) -> None:
        state = await self.login_state_repository.get_login_state(user.id)
        failed_count = state.failed_login_count + 1
        locked_until = None
        action = "login_failed"
        detail = {"failed_login_count": failed_count}

        if failed_count >= self.failed_login_threshold:
            locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=self.lockout_minutes,
            )
            action = "account_locked"
            detail["locked_until"] = locked_until.isoformat()

        await self.login_state_repository.register_login_failure(
            user.id,
            failed_count,
            locked_until,
        )
        await self._log(user, action, detail, ip_address)
        if locked_until is not None:
            raise AccountLockedError()
        raise AuthenticationError()

    async def _log(
        self,
        user: User,
        action: str,
        detail: dict,
        ip_address: str | None,
    ) -> None:
        await self.audit_logger.log(
            action=action,
            actor_id=user.id,
            actor_role=_role_value(user.role),
            resource_type="user",
            resource_id=user.id,
            detail=detail,
            ip_address=ip_address,
        )


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)
