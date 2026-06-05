from datetime import datetime

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
    url: str
    file_type: str
    expires_in: int = 300


class MessageResponse(BaseModel):
    message: str

