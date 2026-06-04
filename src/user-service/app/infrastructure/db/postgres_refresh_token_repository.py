from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.auth.refresh_token_use_case import RefreshTokenRecord
from app.infrastructure.db.models import RefreshTokenModel


class PostgresRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        self.session.add(
            RefreshTokenModel(
                id=UUID(token_id),
                user_id=UUID(user_id),
                token_hash=token_hash,
                expires_at=expires_at,
            ),
        )
        await self.session.commit()

    async def get_by_id(self, token_id: str) -> RefreshTokenRecord | None:
        result = await self.session.execute(
            select(RefreshTokenModel).where(RefreshTokenModel.id == UUID(token_id)),
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return RefreshTokenRecord(
            id=str(model.id),
            user_id=str(model.user_id),
            token_hash=model.token_hash,
            expires_at=model.expires_at,
            revoked_at=model.revoked_at,
        )

    async def revoke(self, token_id: str) -> None:
        result = await self.session.execute(
            select(RefreshTokenModel).where(RefreshTokenModel.id == UUID(token_id)),
        )
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.revoked_at = datetime.now(timezone.utc)
        await self.session.commit()

