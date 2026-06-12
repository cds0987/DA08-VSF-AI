from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol
from uuid import UUID

from app.application.exceptions import InactiveUserError, InvalidTokenError
from app.application.security import PasswordHasher, TokenService
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class RefreshTokenRecord:
    id: str
    user_id: str
    token_hash: str
    expires_at: datetime
    revoked_at: Optional[datetime] = None


@dataclass(frozen=True)
class RefreshResult:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRepository(Protocol):
    async def get_by_id(self, token_id: str) -> Optional[RefreshTokenRecord]:
        ...

    async def revoke(self, token_id: str) -> None:
        ...


class RefreshTokenIssuer(Protocol):
    async def issue(self, user_id: str) -> str:
        ...


class RefreshTokenUseCase:
    def __init__(
        self,
        user_repository: UserRepository,
        refresh_token_repository: RefreshTokenRepository,
        refresh_token_issuer: RefreshTokenIssuer,
        password_hasher: PasswordHasher,
        token_service: TokenService,
    ) -> None:
        self.user_repository = user_repository
        self.refresh_token_repository = refresh_token_repository
        self.refresh_token_issuer = refresh_token_issuer
        self.password_hasher = password_hasher
        self.token_service = token_service

    async def execute(self, refresh_token: str) -> RefreshResult:
        token_id, secret = self._split_token(refresh_token)
        record = await self.refresh_token_repository.get_by_id(token_id)
        now = datetime.now(timezone.utc)
        if (
            record is None
            or record.revoked_at is not None
            or record.expires_at <= now
            or not self.password_hasher.verify(secret, record.token_hash)
        ):
            raise InvalidTokenError()

        # Revoke before user checks so a compromised token can't be replayed
        await self.refresh_token_repository.revoke(record.id)

        user = await self.user_repository.get_by_id(record.user_id)
        if user is None:
            raise InvalidTokenError()
        if not user.is_active:
            raise InactiveUserError()

        access_token = self.token_service.create_access_token(user)
        new_refresh = await self.refresh_token_issuer.issue(user.id)
        return RefreshResult(
            access_token=access_token.token,
            refresh_token=new_refresh,
        )

    def _split_token(self, raw_token: str) -> tuple[str, str]:
        parts = raw_token.split(".", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise InvalidTokenError()
        try:
            UUID(parts[0])
        except ValueError as exc:
            raise InvalidTokenError() from exc
        return parts[0], parts[1]

