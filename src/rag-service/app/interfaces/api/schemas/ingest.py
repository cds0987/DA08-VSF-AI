from pydantic import BaseModel


class IngestRequest(BaseModel):
    document_id: str
    document_name: str
    file_type: str
    markdown: str
    source_uri: str | None = None
    artifact_uri: str | None = None


class IngestResponse(BaseModel):
    document_id: str
    status: str
    chunk_count: int
    message: str
