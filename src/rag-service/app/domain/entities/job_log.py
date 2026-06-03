from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class JobLog:
    document_id: str
    status: str
    stage: str
    created_at: datetime
    correlation_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
