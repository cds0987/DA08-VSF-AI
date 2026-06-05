from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class DocumentStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


@dataclass(frozen=True)
class Document:
    id: str
    name: str
    file_type: str
    gcs_key: str
    status: DocumentStatus
    uploaded_by: str
    created_at: datetime
    chunk_count: int = 0
    error_message: Optional[str] = None
    classification: str = "internal"
    allowed_departments: list[str] = field(default_factory=list)
    allowed_user_ids: list[str] = field(default_factory=list)

