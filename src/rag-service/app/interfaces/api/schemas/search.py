from typing import List

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    question: str
    correlation_id: str | None = None


class SearchLineageResponse(BaseModel):
    source_uri: str
    artifact_uri: str


class SearchResultResponse(BaseModel):
    correlation_id: str
    unit_id: str
    document_id: str
    display_name: str
    caption: str
    content: str
    heading_path: List[str] = Field(default_factory=list)
    lineage: SearchLineageResponse
    page_number: int
    score: float
    rerank_score: float


class SearchResponse(BaseModel):
    results: List[SearchResultResponse]
