from pydantic import BaseModel


class UploadResponse(BaseModel):
    document_id: str
    status: str             # "queued" (Admin upload) | "pending" (End User upload)
    message: str
