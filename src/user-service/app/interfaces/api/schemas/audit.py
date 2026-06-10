from pydantic import BaseModel


class AuditLogItem(BaseModel):
    id: str
    actor_id: str
    actor_role: str
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    detail: dict | None = None
    ip_address: str | None = None
    created_at: str


class AuditLogList(BaseModel):
    items: list[AuditLogItem]
    total: int
