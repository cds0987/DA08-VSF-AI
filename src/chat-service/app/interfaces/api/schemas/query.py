from pydantic import BaseModel
from typing import List


class Source(BaseModel):
    document_name: str
    page_number: int
    score: float
    chunk_text: str         # đoạn văn bản gốc được retrieve — dùng để highlight trên viewer


class QueryRequest(BaseModel):
    question: str
    user_id: str


class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    session_id: str
