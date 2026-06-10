from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import AuditLogModel


class PostgresAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        limit: int,
        offset: int,
    ) -> tuple[list[AuditLogModel], int]:
        total = await self.session.scalar(
            select(func.count()).select_from(AuditLogModel),
        )
        result = await self.session.execute(
            select(AuditLogModel)
            .order_by(AuditLogModel.created_at.desc())
            .limit(limit)
            .offset(offset),
        )
        return list(result.scalars().all()), int(total or 0)

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
        self.session.add(
            AuditLogModel(
                actor_id=UUID(actor_id),
                actor_role=_role_value(actor_role),
                action=action,
                resource_type=resource_type,
                resource_id=UUID(resource_id) if resource_id else None,
                detail=detail,
                ip_address=ip_address,
            ),
        )
        await self.session.commit()


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)

