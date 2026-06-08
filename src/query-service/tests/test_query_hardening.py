from dataclasses import dataclass

import pytest

from app.application.ports import AuthenticatedUser
from app.application.tool_decision import ToolDecision
from app.application.use_cases.query.orchestration import QueryOrchestrationUseCase
from app.infrastructure.cache.semantic_cache import InMemorySemanticCache
from app.infrastructure.config import Settings


@dataclass(frozen=True)
class StubSearchResult:
    chunk_id: str
    document_id: str
    document_name: str
    caption: str
    parent_text: str
    heading_path: list[str]
    score: float
    page_number: int | None = None
    source_gcs_uri: str = ""
    markdown_gcs_uri: str = ""


class StubConversationRepository:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.summary: str | None = None

    async def get_context(self, user_id: str, recent_k: int = 5):
        from app.domain.entities.conversation import ConversationContext, Message
        from datetime import datetime, timezone

        recent = [
            Message(role=role, content=content, created_at=datetime.now(timezone.utc))
            for role, content in self.messages[-recent_k * 2 :]
        ]
        return ConversationContext(summary=self.summary, recent_messages=recent)

    async def save_message(self, user_id: str, role: str, content: str) -> None:
        self.messages.append((role, content))

    async def save_message_detail(self, user_id: str, role: str, content: str, **kwargs) -> None:
        self.messages.append((role, content))

    async def update_summary(self, user_id: str, summary: str) -> None:
        self.summary = summary

    async def clear_history(self, user_id: str) -> None:
        self.messages.clear()
        self.summary = None

    async def save_feedback(self, session_id: str, score: int) -> None:
        return None


class StubAccessRepository:
    async def get_allowed_doc_ids(self, user_id: str, role: str, department: str):
        return ["allowed-doc"]

    async def upsert_access(self, *args, **kwargs) -> None:
        return None

    async def delete_access(self, document_id: str) -> None:
        return None


class CapturingMcpClient:
    def __init__(self, results: list[StubSearchResult]) -> None:
        self.results = results
        self.last_top_k = None
        self.last_generic_call = None

    async def list_tools(self) -> list[str]:
        return ["rag_search"]

    async def list_tool_specs(self):
        from app.application.ports import ToolSpec

        return [
            ToolSpec(
                name="summary_tool",
                description="Summary tool",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "user_id": {"type": "string"},
                    },
                },
            )
        ]

    async def call_tool(self, name: str, arguments: dict):
        self.last_generic_call = {"name": name, "arguments": dict(arguments)}
        return {"summary": "summary from tool"}

    async def rag_search(self, query: str, document_ids: list[str], top_k: int = 5):
        self.last_top_k = top_k
        return self.results

    async def hr_query(self, user_id: str, intent: str):
        raise AssertionError("hr_query should not be called")


class StubOpenAIClient:
    async def stream_answer(self, *args, **kwargs):
        yield "answer"


class StubDecisionClient:
    async def choose_tool(self, *args, **kwargs):
        return ToolDecision(tool_name="rag_search", arguments={})


class StubGenericDecisionClient:
    async def choose_tool(self, *args, **kwargs):
        return ToolDecision(
            tool_name="summary_tool",
            arguments={"query": "hello", "user_id": "spoofed"},
        )


@pytest.mark.asyncio
async def test_rag_results_are_post_filtered_by_acl_before_sources_are_returned():
    mcp_client = CapturingMcpClient(
        [
            StubSearchResult(
                chunk_id="denied-chunk",
                document_id="denied-doc",
                document_name="Denied.pdf",
                caption="Denied",
                parent_text="secret",
                heading_path=["Denied"],
                score=0.99,
                source_gcs_uri="gs://denied.pdf",
            )
        ]
    )
    use_case = QueryOrchestrationUseCase(
        settings=Settings(_env_file=None, llm_mode="mock", rag_result_limit=3),
        conversation_repo=StubConversationRepository(),
        document_access_repo=StubAccessRepository(),
        semantic_cache=InMemorySemanticCache(ttl_seconds=60, threshold=0.95),
        mcp_client=mcp_client,
        openai_client=StubOpenAIClient(),
        tool_decision_client=StubDecisionClient(),
    )

    events = [
        event
        async for event in use_case.stream(
            "show secret",
            AuthenticatedUser(
                id="user-1",
                email="user@example.com",
                role="user",
                department="HR",
            ),
        )
    ]

    assert mcp_client.last_top_k == 3
    assert events[-1]["fallback"] is True
    assert events[-1]["sources"] == []


@pytest.mark.asyncio
async def test_summary_never_uses_fixed_mock_text():
    repo = StubConversationRepository()
    use_case = QueryOrchestrationUseCase(
        settings=Settings(_env_file=None, llm_mode="mock", rag_result_limit=3),
        conversation_repo=repo,
        document_access_repo=StubAccessRepository(),
        semantic_cache=InMemorySemanticCache(ttl_seconds=60, threshold=0.95),
        mcp_client=CapturingMcpClient(
            [
                StubSearchResult(
                    chunk_id="allowed-chunk",
                    document_id="allowed-doc",
                    document_name="Allowed.pdf",
                    caption="Allowed",
                    parent_text="allowed context",
                    heading_path=["Allowed"],
                    score=0.99,
                    source_gcs_uri="gs://allowed.pdf",
                )
            ]
        ),
        openai_client=StubOpenAIClient(),
        tool_decision_client=StubDecisionClient(),
    )
    user = AuthenticatedUser(id="user-1", email="u@example.com", role="user", department="HR")

    for index in range(5):
        [event async for event in use_case.stream(f"real question {index}", user)]

    assert repo.summary is None or "Tóm tắt mock" not in repo.summary
    if repo.summary:
        assert "real question" in repo.summary


@pytest.mark.asyncio
async def test_native_generic_tool_injects_reserved_user_id():
    mcp_client = CapturingMcpClient([])
    use_case = QueryOrchestrationUseCase(
        settings=Settings(_env_file=None, llm_mode="mock", tool_routing_mode="native"),
        conversation_repo=StubConversationRepository(),
        document_access_repo=StubAccessRepository(),
        semantic_cache=InMemorySemanticCache(ttl_seconds=60, threshold=0.95),
        mcp_client=mcp_client,
        openai_client=StubOpenAIClient(),
        tool_decision_client=StubGenericDecisionClient(),
    )
    events = [
        event
        async for event in use_case.stream(
            "show my summary",
            AuthenticatedUser(
                id="user-42",
                email="user@example.com",
                role="user",
                department="HR",
            ),
        )
    ]

    assert events[-1]["done"] is True
    assert mcp_client.last_generic_call == {
        "name": "summary_tool",
        "arguments": {
            "query": "hello",
            "user_id": "user-42",
        },
    }
