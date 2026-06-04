from datetime import datetime

from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: str
    event: str
    message: str
    doc_id: str | None
    is_read: bool
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationItem]
    total: int


class UnreadCount(BaseModel):
    unread: int


class DocNewEventRequest(BaseModel):
    doc_id: str
    document_name: str
    classification: str
    allowed_departments: list[str] = []
    allowed_user_ids: list[str] = []
