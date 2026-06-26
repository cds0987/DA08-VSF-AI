from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    # document_ids = danh sách doc-id ACL-allowed của caller. None/rỗng => không có
    # quyền => kết quả rỗng (ACL fail-closed, đối xứng mcp reader). KHÔNG phải "all".
    document_ids: list[str] | None = None
    top_k: int = Field(default=20, ge=1)


class SearchCandidateResponse(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    caption: str
    child_text: str
    parent_text: str
    heading_path: list[str]
    score: float
    page_number: int | None = None
    source_gcs_uri: str
    markdown_gcs_uri: str


class SearchResponse(BaseModel):
    candidates: list[SearchCandidateResponse]
