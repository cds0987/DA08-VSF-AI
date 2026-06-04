from dataclasses import dataclass
from datetime import datetime


@dataclass
class Notification:
    id: str
    user_id: str
    event: str
    message: str
    doc_id: str | None
    is_read: bool
    created_at: datetime
