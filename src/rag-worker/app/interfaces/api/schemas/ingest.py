from datetime import datetime
import os

from pydantic import BaseModel, model_validator


class IngestRequest(BaseModel):
    document_id: str
    document_name: str
    file_type: str
    markdown: str | None = None
    source_uri: str | None = None
    artifact_uri: str | None = None
    correlation_id: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "IngestRequest":
        if not self.markdown and not self.source_uri:
            raise ValueError("either markdown or source_uri is required")
        if self.markdown is not None:
            max_markdown_bytes = int(os.getenv("MAX_MARKDOWN_BYTES", str(512 * 1024)))
            if len(self.markdown.encode("utf-8")) > max_markdown_bytes:
                raise ValueError("markdown payload exceeds MAX_MARKDOWN_BYTES")
        return self


class IngestResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    chunk_count: int = 0
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


class IngestJobResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    claim_id: str | None = None
    attempt: int
    chunk_count: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
