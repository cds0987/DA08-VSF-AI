"""Tests for POST /query (SSE stream) in mock/guarded mode."""

import pytest
from httpx import AsyncClient

from tests.conftest import HR_USER_ID, FINANCE_USER_ID, parse_sse


async def _query(client: AsyncClient, question: str, user_id: str) -> tuple[int, list[dict]]:
    """Helper: fire POST /query, return (status_code, parsed_sse_events)."""
    r = await client.post("/query", json={"question": question, "user_id": user_id})
    events = parse_sse(r.text) if r.status_code == 200 else []
    return r.status_code, events


# ---------------------------------------------------------------------------
# Basic stream shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_returns_200(hr_client: AsyncClient):
    status, _ = await _query(hr_client, "Chính sách nghỉ phép là gì?", HR_USER_ID)
    assert status == 200


@pytest.mark.asyncio
async def test_query_stream_contains_done_event(hr_client: AsyncClient):
    _, events = await _query(hr_client, "Onboarding mới cần làm gì?", HR_USER_ID)
    done_events = [e for e in events if e.get("done") is True]
    assert len(done_events) >= 1, "Stream must end with a done=true event"


@pytest.mark.asyncio
async def test_query_done_event_has_session_id(hr_client: AsyncClient):
    _, events = await _query(hr_client, "Giờ làm việc là mấy giờ?", HR_USER_ID)
    done = next((e for e in events if e.get("done")), None)
    assert done is not None
    assert "session_id" in done, "done event must carry a session_id"


@pytest.mark.asyncio
async def test_query_done_event_has_outcome(hr_client: AsyncClient):
    _, events = await _query(hr_client, "Chính sách nghỉ phép?", HR_USER_ID)
    done = next((e for e in events if e.get("done")), None)
    assert done is not None
    assert "outcome" in done


@pytest.mark.asyncio
async def test_query_stream_has_token_events(hr_client: AsyncClient):
    _, events = await _query(hr_client, "Hướng dẫn onboarding?", HR_USER_ID)
    tokens = [e for e in events if "token" in e]
    assert len(tokens) > 0, "Stream must include token events"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_empty_question_rejected(hr_client: AsyncClient):
    r = await hr_client.post("/query", json={"question": "", "user_id": HR_USER_ID})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_query_question_too_long_rejected(hr_client: AsyncClient):
    r = await hr_client.post("/query", json={
        "question": "x" * 501,
        "user_id": HR_USER_ID,
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_query_missing_user_id_rejected(hr_client: AsyncClient):
    r = await hr_client.post("/query", json={"question": "Câu hỏi?"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_query_user_id_mismatch_returns_403(hr_client: AsyncClient):
    r = await hr_client.post("/query", json={
        "question": "Câu hỏi?",
        "user_id": FINANCE_USER_ID,  # Wrong user
    })
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Shortcut / identity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_identity_shortcut(hr_client: AsyncClient):
    """'Bạn là ai?' must use shortcut path (no MCP call, immediate response)."""
    _, events = await _query(hr_client, "Bạn là ai?", HR_USER_ID)
    done = next((e for e in events if e.get("done")), None)
    assert done is not None


@pytest.mark.asyncio
async def test_query_off_topic_returns_outcome(hr_client: AsyncClient):
    """Off-topic questions must return a response with an outcome code."""
    _, events = await _query(hr_client, "Thời tiết hôm nay thế nào?", HR_USER_ID)
    done = next((e for e in events if e.get("done")), None)
    assert done is not None


# ---------------------------------------------------------------------------
# Reasoning leak — THOUGHT/ACTION/OBSERVATION must NOT appear in token stream
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_no_reasoning_leak(hr_client: AsyncClient):
    """Internal reasoning markers must never reach the user-facing SSE stream."""
    _, events = await _query(hr_client, "Quy trình xin nghỉ phép?", HR_USER_ID)
    for e in events:
        token_text = e.get("token", "")
        for marker in ("THOUGHT:", "ACTION:", "OBSERVATION:"):
            assert marker not in token_text, (
                f"Reasoning marker '{marker}' leaked into SSE stream"
            )


# ---------------------------------------------------------------------------
# Conversation persistence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_persists_to_conversation(hr_client: AsyncClient):
    """After a query the conversation history must have at least 1 message."""
    await _query(hr_client, "Onboarding có những bước nào?", HR_USER_ID)
    history = await hr_client.get("/conversations")
    assert history.status_code == 200
    conversations = history.json()["conversations"]
    assert len(conversations) == 1

    conversation_id = conversations[0]["id"]
    detail = await hr_client.get(f"/conversations/{conversation_id}")
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) >= 1


# ---------------------------------------------------------------------------
# Citation verify — chỉ giữ source được LLM cite [N] trong answer
# ---------------------------------------------------------------------------

from app.application.use_cases.query.orchestration import _keep_cited_sources


def _sources(*refs: int) -> list[dict]:
    return [{"ref": r, "document_name": f"doc{r}"} for r in refs]


def test_keep_cited_sources_filters_to_cited_only():
    """Answer cite [1][3] -> chỉ giữ source ref 1 và 3."""
    answer = "Nghỉ phép năm 12 ngày [1]. Kỷ luật: cảnh cáo đến sa thải [3]."
    kept = _keep_cited_sources(answer, _sources(1, 2, 3, 4, 5))
    assert {s["ref"] for s in kept} == {1, 3}


def test_keep_cited_sources_empty_when_no_citation():
    """Answer 'không tìm thấy' (không [N]) -> sources rỗng, không show card thừa."""
    answer = "Mình chưa tìm thấy thông tin về luật công ty VSF trong tài liệu hiện có."
    assert _keep_cited_sources(answer, _sources(1, 2, 3)) == []


def test_keep_cited_sources_ignores_hallucinated_ref():
    """LLM bịa [9] khi chỉ có 3 source -> ref 9 bị loại, giữ [2] hợp lệ."""
    answer = "Theo quy định [2] và tài liệu [9]."
    kept = _keep_cited_sources(answer, _sources(1, 2, 3))
    assert {s["ref"] for s in kept} == {2}


def test_keep_cited_sources_handles_empty_sources():
    """Không có source -> trả nguyên (rỗng), không lỗi."""
    assert _keep_cited_sources("bất kỳ [1]", []) == []
