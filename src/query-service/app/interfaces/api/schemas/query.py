from typing import Literal

from pydantic import BaseModel, Field


class Source(BaseModel):
    document_name: str
    caption: str
    heading_path: list[str]
    score: float
    source_gcs_uri: str


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    user_id: str
    trace_session: str | None = None
    conversation_title: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    session_id: str


class FeedbackRequest(BaseModel):
    session_id: str
    score: Literal[1, -1]
    trace_id: str | None = None
