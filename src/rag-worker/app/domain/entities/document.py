from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


@dataclass
class Document:
    id: str
    name: str
    file_type: str
    s3_key: str
    status: DocumentStatus
    created_at: datetime
    chunk_count: int = 0
    error_message: str | None = None


@dataclass
class Chunk:
    id: str
    document_id: str
    parent_id: str
    child_text: str
    parent_text: str
    page_number: int
    section_title: str = ""
