from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    PENDING = "pending"         # End User upload, chờ Admin approve
    QUEUED = "queued"           # Admin upload trực tiếp, hoặc đã được approve
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"       # Admin reject


@dataclass
class Document:
    id: str
    name: str
    file_type: str              # pdf, docx, txt, xlsx, csv, pptx, md
    s3_key: str
    status: DocumentStatus
    uploaded_by: str            # user_id
    created_at: datetime
    chunk_count: int = 0
    error_message: Optional[str] = None
    classification: str = "internal"                                # public | internal | secret | top_secret
    allowed_departments: List[str] = field(default_factory=list)   # bắt buộc nếu secret
    allowed_user_ids: List[str] = field(default_factory=list)      # bắt buộc nếu top_secret


@dataclass
class Chunk:
    id: str
    document_id: str
    parent_id: str              # parent chunk chứa context đầy đủ hơn
    child_text: str             # 128–256 tokens — dùng để embed
    parent_text: str            # 512–1024 tokens — đưa vào LLM prompt
    page_number: int
    section_title: str = ""
