from typing import List, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    # Shape theo contract NATS `rag.search` (docs/contracts.md, api-spec.md):
    #   { query_text, document_ids, top_k }
    query_text: str
    document_ids: Optional[List[str]] = None  # ACL filter (Query Service inject); None = fail-secure
    top_k: int = 5
    correlation_id: str | None = None  # tracing — ngoài contract docs, optional


class SearchResultResponse(BaseModel):
    # = contract SearchResult (docs/contracts.md §rag-worker — Domain)
    chunk_id: str
    document_id: str
    document_name: str
    caption: str
    parent_text: str
    heading_path: List[str] = Field(default_factory=list)
    score: float
    page_number: Optional[int] = None
    source_s3_uri: str = ""
    markdown_s3_uri: str = ""


class SearchResponse(BaseModel):
    results: List[SearchResultResponse]
