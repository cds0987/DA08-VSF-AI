from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    document_id: str
    status: str
    message: str


class DocumentItem(BaseModel):
    id: str
    name: str
    file_type: str
    status: str
    classification: str
    uploaded_by: str
    chunk_count: int
    created_at: datetime


class DocumentDetail(DocumentItem):
    error_message: str | None = None
    allowed_departments: list[str] = Field(default_factory=list)
    allowed_user_ids: list[str] = Field(default_factory=list)


class DocumentList(BaseModel):
    items: list[DocumentItem]
    total: int = Field(ge=0)


class DocumentFileResponse(BaseModel):
    url: str = Field(min_length=1)
    file_type: Literal["pdf", "docx", "txt", "xlsx", "csv", "pptx", "md"]
    expires_in: int = Field(default=300, gt=0)


class MessageResponse(BaseModel):
    message: str

