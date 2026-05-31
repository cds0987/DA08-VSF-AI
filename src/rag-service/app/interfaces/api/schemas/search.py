from pydantic import BaseModel
from typing import List


class SearchRequest(BaseModel):
    question: str
    user_id: str
    user_role: str
    user_department: str


class SearchResultResponse(BaseModel):
    chunk_id: str
    document_name: str
    page_number: int
    section_title: str
    parent_text: str
    score: float
    rerank_score: float


class SearchResponse(BaseModel):
    results: List[SearchResultResponse]
