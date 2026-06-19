"""MemoryProvider ABC — build ngữ cảnh hội thoại cho orchestrator/synthesize.

load(messages) -> list[(role, content)] đã xử lý (cắt/nén). messages đầu vào là
list[(role, content)] thô gần nhất từ conversation_repo.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

Message = tuple[str, str]


class MemoryProvider(ABC):
    name: str = ""

    def __init__(self, *, keep_recent: int = 4, summarize_after: int = 8,
                 make_model: Callable[[str], Any] | None = None) -> None:
        self.keep_recent = keep_recent
        self.summarize_after = summarize_after
        self.make_model = make_model

    @abstractmethod
    async def load(self, messages: list[Message]) -> list[Message]:
        raise NotImplementedError
