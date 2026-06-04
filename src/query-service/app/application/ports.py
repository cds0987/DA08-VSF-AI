from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    role: str
    department: str
    is_active: bool = True


class SearchResultLike(Protocol):
    chunk_id: str
    document_id: str
    document_name: str
    caption: str
    parent_text: str
    heading_path: list[str]
    score: float
    page_number: int | None
    source_s3_uri: str
    markdown_s3_uri: str


class HrQueryResultLike(Protocol):
    intent: str
    summary: str


class MCPToolClient(Protocol):
    async def list_tools(self) -> list[str]:
        ...

    async def rag_search(
        self,
        query: str,
        document_ids: list[str],
        top_k: int = 5,
    ) -> list[SearchResultLike]:
        ...

    async def hr_query(self, user_id: str, intent: str) -> HrQueryResultLike:
        ...


class LLMStreamingClient(Protocol):
    async def stream_answer(
        self,
        question: str,
        context: str,
        recent_messages: list[tuple[str, str]],
        sources: Sequence[SearchResultLike],
        is_hr_answer: bool = False,
    ) -> AsyncIterator[str]:
        ...


class SemanticCache(Protocol):
    async def get(self, namespace: str, question: str) -> tuple[str, list[dict]] | None:
        ...

    async def put(self, namespace: str, question: str, answer: str, sources: list[dict]) -> None:
        ...
