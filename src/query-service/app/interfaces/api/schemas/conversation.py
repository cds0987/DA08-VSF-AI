from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ConversationMessage(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime
    session_id: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    feedback: int | None = None


class ConversationSummary(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationList(BaseModel):
    conversations: list[ConversationSummary]
    messages: list[ConversationMessage] = Field(default_factory=list)


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessage]


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("Title must not be blank")
        return title


class ConversationMutationResponse(BaseModel):
    message: str


class ClearConversationResponse(BaseModel):
    message: str
