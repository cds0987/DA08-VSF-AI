from datetime import datetime

from pydantic import BaseModel


class ConversationMessage(BaseModel):
    role: str
    content: str
    created_at: datetime


class ConversationHistory(BaseModel):
    messages: list[ConversationMessage]


class ClearConversationResponse(BaseModel):
    message: str
