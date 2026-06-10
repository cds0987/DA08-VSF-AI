from fastapi import APIRouter, Depends, Query

from app.domain.entities.user import User
from app.infrastructure.db.models import AuditLogModel
from app.infrastructure.db.postgres_audit_log_repository import PostgresAuditLogRepository
from app.interfaces.api.dependencies import get_audit_logger, require_admin
from app.interfaces.api.schemas.audit import AuditLogItem, AuditLogList


router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=AuditLogList)
async def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    repo: PostgresAuditLogRepository = Depends(get_audit_logger),
) -> AuditLogList:
    rows, total = await repo.list(limit=limit, offset=offset)
    return AuditLogList(items=[_to_item(row) for row in rows], total=total)


def _to_item(row: AuditLogModel) -> AuditLogItem:
    return AuditLogItem(
        id=str(row.id),
        actor_id=str(row.actor_id),
        actor_role=row.actor_role,
        action=row.action,
        resource_type=row.resource_type,
        resource_id=str(row.resource_id) if row.resource_id else None,
        detail=row.detail,
        ip_address=row.ip_address,
        created_at=row.created_at.isoformat(),
    )
