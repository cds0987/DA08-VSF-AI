from pydantic import BaseModel
from typing import List, Optional


class IngestRequest(BaseModel):
    document_id: str
    classification: str = "internal"
    allowed_departments: List[str] = []
    allowed_user_ids: List[str] = []


class IngestResponse(BaseModel):
    document_id: str
    status: str
    message: str
