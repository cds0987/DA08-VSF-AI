"""Unit: auto-title fire-and-forget — KHÔNG chặn _save_assistant (-> event `done` nhanh).

_maybe_auto_title chạy nền sau turn 1: sinh title ngắn bằng LLM rẻ rồi update DB.
Không được chặn luồng chính (tương tự _maybe_update_summary).
"""
from __future__ import annotations

import asyncio
from time import perf_counter

import pytest

from app.application.use_cases.query.orchestration import (
    QueryOrchestrationUseCase,
    _ACTIVE_CONVERSATION_ID,
)
from app.infrastructure.config import get_settings
from app.domain.entities.conversation import ConversationContext, Message
from datetime import datetime, timezone


class _Stored:
    id = "m1"


class _Repo:
    def __init__(self):
        self.updated_title: str | None = None

    async def save_message_detail(self, **kwargs):
        return _Stored()

    async def get_context(self, user_id, recent_k=5, conversation_id=None):
        now = datetime.now(timezone.utc)
        return ConversationContext(
            summary=None,
            recent_messages=[
                Message(role="user", content="câu hỏi", created_at=now),
                Message(role="assistant", content="câu trả lời", created_at=now),
            ],
        )

    async def update_title(self, user_id, conversation_id, title):
        self.updated_title = title
        return True


def _make_uc(title_generator=None) -> tuple[QueryOrchestrationUseCase, _Repo]:
    repo = _Repo()
    uc = QueryOrchestrationUseCase(
        settings=get_settings(),
        conversation_repo=repo,
        document_access_repo=object(),
        semantic_cache=object(),
        mcp_client=object(),
        openai_client=object(),
        route_decision_provider=object(),
        title_generator=title_generator,
    )
    return uc, repo


@pytest.mark.asyncio
async def test_save_assistant_does_not_block_on_auto_title():
    finished = asyncio.Event()

    class _SlowTitleGen:
        async def generate(self, question: str) -> str:
            await asyncio.sleep(0.2)
            finished.set()
            return "Tiêu đề ngắn"

    uc, repo = _make_uc(title_generator=_SlowTitleGen())

    token = _ACTIVE_CONVERSATION_ID.set("conv-123")
    try:
        t0 = perf_counter()
        mid = await uc._save_assistant("u1", "s1", "answer", [], t0, question="câu hỏi")
        elapsed = perf_counter() - t0
    finally:
        _ACTIVE_CONVERSATION_ID.reset(token)

    assert mid == "m1"
    assert elapsed < 0.15        # KHÔNG đợi title gen 0.2s
    assert not finished.is_set()  # title gen chưa xong
    assert uc._bg_tasks           # ref task được giữ

    await asyncio.wait_for(finished.wait(), timeout=1.0)
    await asyncio.sleep(0)        # cho done_callback chạy
    assert not uc._bg_tasks       # discard sau khi xong


@pytest.mark.asyncio
async def test_auto_title_only_on_turn_1():
    """_maybe_auto_title chỉ chạy khi đúng 2 messages (turn 1)."""
    call_count = 0

    class _CountingTitleGen:
        async def generate(self, question: str) -> str:
            nonlocal call_count
            call_count += 1
            return "Title"

    uc, repo = _make_uc(title_generator=_CountingTitleGen())

    token = _ACTIVE_CONVERSATION_ID.set("conv-123")
    try:
        await uc._maybe_auto_title("u1", "câu hỏi")
    finally:
        _ACTIVE_CONVERSATION_ID.reset(token)

    assert call_count == 1
    assert repo.updated_title == "Title"


@pytest.mark.asyncio
async def test_auto_title_skipped_when_no_generator():
    uc, repo = _make_uc(title_generator=None)
    token = _ACTIVE_CONVERSATION_ID.set("conv-123")
    try:
        await uc._maybe_auto_title("u1", "câu hỏi")
    finally:
        _ACTIVE_CONVERSATION_ID.reset(token)
    assert repo.updated_title is None
