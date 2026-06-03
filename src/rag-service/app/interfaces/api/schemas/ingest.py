from pydantic import BaseModel


class IngestRequest(BaseModel):
    document_id: str
    # Không có field access control: rag-service không enforce phân quyền
    # (search.md §6). Phân loại/scope nếu cần là metadata thụ động do caller quản.


class IngestResponse(BaseModel):
    document_id: str
    status: str
    message: str
