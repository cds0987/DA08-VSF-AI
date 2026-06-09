"""Tests for POST /feedback."""

import pytest
from httpx import AsyncClient

from tests.conftest import HR_USER_ID


async def _seed_session(user_id: str, session_id: str = "test-session-001") -> str:
    """Seed a fake assistant message with a session_id so feedback can reference it."""
    from app.interfaces.api.dependencies import get_conversation_repo
    repo = get_conversation_repo()
    await repo.save_message_detail(
        user_id=user_id,
        role="assistant",
        content="Mỗi nhân viên có 12 ngày nghỉ phép.",
        session_id=session_id,
    )
    return session_id


@pytest.mark.asyncio
async def test_feedback_thumbs_up(hr_client: AsyncClient):
    sid = await _seed_session(HR_USER_ID)
    r = await hr_client.post("/feedback", json={"session_id": sid, "score": 1})
    assert r.status_code == 200
    assert r.json().get("message") == "Feedback recorded"


@pytest.mark.asyncio
async def test_feedback_thumbs_down(hr_client: AsyncClient):
    sid = await _seed_session(HR_USER_ID)
    r = await hr_client.post("/feedback", json={"session_id": sid, "score": -1})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_feedback_invalid_score_rejected(hr_client: AsyncClient):
    sid = await _seed_session(HR_USER_ID)
    r = await hr_client.post("/feedback", json={"session_id": sid, "score": 0})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_feedback_unknown_session_returns_404(hr_client: AsyncClient):
    r = await hr_client.post("/feedback", json={
        "session_id": "nonexistent-session-xyz",
        "score": 1,
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_feedback_requires_auth(client: AsyncClient):
    r = await client.post("/feedback", json={"session_id": "any", "score": 1})
    assert r.status_code == 401
