import pytest

from app.infrastructure.cache.semantic_cache import InMemorySemanticCache
from app.infrastructure.config import get_settings
from app.infrastructure.db.mock_notification_repo import InMemoryNotificationRepository
from app.interfaces.api.dependencies import (
    get_conversation_repo,
    get_current_user,
    get_mcp_client,
    get_orchestration_use_case,
    reset_state_for_tests,
)
from app.infrastructure.auth.auth_service import AuthService


@pytest.mark.asyncio
async def test_semantic_cache_returns_similar_question():
    cache = InMemorySemanticCache(ttl_seconds=3600, threshold=0.95)
    await cache.put("scope-1", "Chính sách nghỉ phép là gì", "answer", [{"document_name": "doc"}])

    cached = await cache.get("scope-1", "Chính sách nghỉ phép là gì")

    assert cached is not None
    assert cached[0] == "answer"


@pytest.mark.asyncio
async def test_semantic_cache_does_not_cross_scope():
    cache = InMemorySemanticCache(ttl_seconds=3600, threshold=0.95)
    await cache.put("admin-scope", "Executive compensation", "answer", [{"document_name": "top"}])

    cached = await cache.get("user-scope", "Executive compensation")

    assert cached is None


@pytest.mark.asyncio
async def test_tool_arguments_are_injected_from_auth_context(tokens):
    reset_state_for_tests()
    settings = get_settings()
    user = await AuthService(settings).authenticate(f"Bearer {tokens['finance']}")
    use_case = get_orchestration_use_case()
    events = [
        event
        async for event in use_case.stream("Finance report guideline", user)
    ]

    last_call = get_mcp_client().last_tool_calls[-1]
    assert events[-1]["done"] is True
    assert last_call.tool_name == "rag_search"
    assert last_call.arguments["document_ids"]
    assert "dddddddd-0003-4000-8000-000000000003" in last_call.arguments["document_ids"]
    assert "user_id" not in last_call.arguments


@pytest.mark.asyncio
async def test_conversation_save_feedback_contract(tokens):
    reset_state_for_tests()
    settings = get_settings()
    user = await AuthService(settings).authenticate(f"Bearer {tokens['hr']}")
    use_case = get_orchestration_use_case()
    events = [event async for event in use_case.stream("Onboarding", user)]
    session_id = events[-1]["session_id"]

    repo = get_conversation_repo()
    await repo.save_feedback(session_id, 1)
    metrics = await repo.metrics()

    assert metrics["feedback"]["up"] == 1


@pytest.mark.asyncio
async def test_notification_repository_contract_methods():
    repo = InMemoryNotificationRepository()
    notification = await repo.save(
        user_id="user-1",
        event="doc_new",
        message="Có tài liệu mới: A",
        doc_id="doc-1",
    )

    assert await repo.unread_count("user-1") == 1
    history = await repo.list_history("user-1")
    assert history == [notification]

    await repo.mark_read(notification.id)
    assert await repo.unread_count("user-1") == 0


@pytest.mark.asyncio
async def test_mcp_contract_returns_chunk_result_and_typed_hr_summary(tokens):
    reset_state_for_tests()
    mcp_client = get_mcp_client()
    rag_results = await mcp_client.rag_search(
        query="Finance report guideline",
        document_ids=["dddddddd-0003-4000-8000-000000000003"],
    )
    hr_result = await mcp_client.hr_query(
        user_id="22222222-2222-4222-8222-222222222222",
        intent="leave_balance",
    )

    assert rag_results[0].chunk_id
    assert rag_results[0].parent_text
    assert not hasattr(rag_results[0], "section_content")
    assert hr_result.intent == "leave_balance"
    assert hr_result.leave_balance is not None
    assert "ngày nghỉ phép" in hr_result.summary
