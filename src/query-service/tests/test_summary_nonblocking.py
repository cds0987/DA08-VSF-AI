"""Unit: summary update fire-and-forget — KHÔNG chặn _save_assistant (-> event `done` nhanh).

Trước đây _maybe_update_summary chạy `await` trong _save_assistant -> hội thoại dài bị treo
~2-4s/lượt vì 1 LLM call gộp summary. Nay chạy nền (create_task) -> _save_assistant trả ngay.
"""
from __future__ import annotations

import asyncio
from time import perf_counter

import pytest

from app.application.use_cases.query.orchestration import QueryOrchestrationUseCase
from app.infrastructure.config import get_settings


class _Stored:
    id = "m1"


class _Repo:
    async def save_message_detail(self, **kwargs):
        return _Stored()


def _make_uc() -> QueryOrchestrationUseCase:
    return QueryOrchestrationUseCase(
        settings=get_settings(),
        conversation_repo=_Repo(),
        document_access_repo=object(),
        semantic_cache=object(),
        mcp_client=object(),
        openai_client=object(),
        route_decision_provider=object(),  # không dùng trong _save_assistant, chỉ qua validation
    )


@pytest.mark.asyncio
async def test_save_assistant_does_not_block_on_summary():
    uc = _make_uc()
    finished = asyncio.Event()

    async def _slow_summary(user_id):
        await asyncio.sleep(0.2)
        finished.set()

    uc._maybe_update_summary = _slow_summary  # type: ignore[method-assign]

    t0 = perf_counter()
    mid = await uc._save_assistant("u1", "s1", "answer", [], t0)
    elapsed = perf_counter() - t0

    assert mid == "m1"
    assert elapsed < 0.15        # KHÔNG đợi summary 0.2s -> fire-and-forget (không chặn `done`)
    assert not finished.is_set()  # summary chưa xong lúc _save_assistant trả về
    assert uc._bg_tasks           # ref task nền được giữ (tránh GC)

    # task nền vẫn hoàn tất sau đó + tự gỡ khỏi set
    await asyncio.wait_for(finished.wait(), timeout=1.0)
    await asyncio.sleep(0)        # cho done_callback chạy
    assert not uc._bg_tasks       # discard sau khi xong
