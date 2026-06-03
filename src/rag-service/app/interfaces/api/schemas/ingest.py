from datetime import datetime

from pydantic import BaseModel


class IngestRequest(BaseModel):
    document_id: str
    document_name: str
    file_type: str
    markdown: str
    source_uri: str | None = None
    artifact_uri: str | None = None
    correlation_id: str | None = None


class IngestResponse(BaseModel):
    document_id: str
    status: str
    chunk_count: int
    message: str


class DocumentResponse(BaseModel):
    document_id: str
    document_name: str
    file_type: str
    source_uri: str
    status: str
    chunk_count: int
    created_at: datetime
    error_message: str | None = None
