from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Protocol
from uuid import uuid4

from app.application.security import PasswordHasher


class RefreshTokenStore(Protocol):
    async def create(
        self,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        ...


class RefreshTokenIssuer:
    def __init__(
        self,
        store: RefreshTokenStore,
        password_hasher: PasswordHasher,
        ttl_days: int = 7,
    ) -> None:
        self.store = store
        self.password_hasher = password_hasher
        self.ttl_days = ttl_days

    async def issue(self, user_id: str) -> str:
        token_id = str(uuid4())
        secret = token_urlsafe(48)
        token_hash = self.password_hasher.hash(secret)
        expires_at = datetime.now(timezone.utc) + timedelta(days=self.ttl_days)
        await self.store.create(
            token_id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        return f"{token_id}.{secret}"

