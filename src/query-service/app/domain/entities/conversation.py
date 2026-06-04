from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Message:
    role: str
    content: str
    created_at: datetime


@dataclass
class ConversationContext:
    summary: Optional[str]
    recent_messages: list[Message]


@dataclass
class Conversation:
    id: str
    user_id: str
    messages: list[Message] = field(default_factory=list)
