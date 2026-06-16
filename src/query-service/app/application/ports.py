from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.application.route_decision import RouteDecision
from app.application.tool_decision import ToolDecision
from app.domain.outcome import Outcome


@dataclass(frozen=True)
class ToolSpec:
    """Tool specification as seen by the model — reserved params already stripped."""
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    role: str
    is_active: bool = True
    account_type: str = "internal"
    department: str = ""


class SearchResultLike(Protocol):
    chunk_id: str
    document_id: str
    document_name: str
    caption: str
    child_text: str
    parent_text: str
    heading_path: list[str]
    score: float
    page_number: int | None
    source_gcs_uri: str
    markdown_gcs_uri: str


class HrQueryResultLike(Protocol):
    intent: str
    summary: str


class MCPToolClient(Protocol):
    async def list_tools(self) -> list[str]:
        ...

    async def list_tool_specs(self) -> list[ToolSpec]:
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

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...


class LLMStreamingClient(Protocol):
    async def stream_answer(
        self,
        question: str,
        context: str,
        recent_messages: list[tuple[str, str]],
        sources: Sequence[SearchResultLike],
        is_hr_answer: bool = False,
        outcome: Outcome | None = None,
    ) -> AsyncIterator[str]:
        ...


class ToolDecisionClient(Protocol):
    async def choose_tool(
        self,
        question: str,
        recent_messages: list[tuple[str, str]],
        available_tools: Sequence[str],
    ) -> ToolDecision:
        ...


class RouteDecisionProvider(Protocol):
    async def choose_route(
        self,
        question: str,
        recent_messages: list[tuple[str, str]],
        available_tools: Sequence[str],
    ) -> RouteDecision:
        ...


class SemanticCache(Protocol):
    async def get(self, namespace: str, question: str) -> tuple[str, list[dict]] | None:
        ...

    async def put(self, namespace: str, question: str, answer: str, sources: list[dict]) -> None:
        ...


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    arguments: dict


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    success: bool
    data: str
    error: str | None = None


@dataclass(frozen=True)
class ReActMessage:
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_name: str | None = None


@dataclass(frozen=True)
class ReActOutput:
    is_final_answer: bool
    content: str
    tool_calls: list[ToolCall]
    sources: list[dict]
    reasoning: str


class AgentLLMClient(Protocol):
    async def react_step(
        self,
        messages: list[ReActMessage],
        available_tools: list[str],
    ) -> ReActOutput:
        ...
