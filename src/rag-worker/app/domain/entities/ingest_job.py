from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class IngestJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"


@dataclass
class IngestJob:
    id: str
    document_id: str
    document_name: str
    file_type: str
    source_uri: str | None
    markdown: str | None
    artifact_uri: str | None
    correlation_id: str | None
    status: IngestJobStatus
    created_at: datetime
    updated_at: datetime
    claim_id: str | None = None
    attempt: int = 0
    chunk_count: int = 0
    error_message: str | None = None
