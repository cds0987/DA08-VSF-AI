from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class Message:
    role: str           # "user" | "assistant"
    content: str
    created_at: datetime


@dataclass
class ConversationContext:
    summary: Optional[str]          # LLM-generated summary của các turns cũ (None nếu chưa đủ để compress)
    recent_messages: List[Message]  # 5 turns gần nhất giữ nguyên verbatim


@dataclass
class Conversation:
    id: str
    user_id: str
    messages: List[Message] = field(default_factory=list)
