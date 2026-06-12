from datetime import datetime, timezone
from uuid import UUID

from app.application.exceptions import InvalidTokenError
from app.application.security import PasswordHasher
from app.application.use_cases.auth.refresh_token_use_case import RefreshTokenRepository


class LogoutUseCase:
    def __init__(
        self,
        refresh_token_repository: RefreshTokenRepository,
        password_hasher: PasswordHasher,
    ) -> None:
        self.refresh_token_repository = refresh_token_repository
        self.password_hasher = password_hasher

    async def execute(self, refresh_token: str) -> None:
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
        await self.refresh_token_repository.revoke(record.id)

    def _split_token(self, raw_token: str) -> tuple[str, str]:
        parts = raw_token.split(".", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise InvalidTokenError()
        try:
            UUID(parts[0])
        except ValueError as exc:
            raise InvalidTokenError() from exc
        return parts[0], parts[1]
