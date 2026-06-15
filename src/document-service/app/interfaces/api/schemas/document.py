from datetime import datetime

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    document_id: str
    status: str
    message: str


class SupportedFormatsResponse(BaseModel):
    # extensions = ALLOWED_EXTENSIONS (manifest rag-worker ∩ allow_list chính sách).
    # Nguồn để frontend dựng accept filter + validation, không hardcode lệch backend.
    extensions: list[str]
    max_file_bytes: int


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
    # file_type không ràng Literal cố định: tập loại hợp lệ nay động theo
    # ALLOWED_EXTENSIONS (manifest rag-worker ∩ allow_list). Validate đã làm ở
    # use case (đối chiếu ALLOWED_EXTENSIONS) nên schema chỉ cần str.
    url: str = Field(min_length=1)
    file_type: str = Field(min_length=1)
    expires_in: int = Field(default=300, gt=0)


class MessageResponse(BaseModel):
    message: str

