from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import HR_USER_ID, parse_sse


@pytest.mark.asyncio
async def test_history_keeps_conversation_and_answer_session_ids(hr_client: AsyncClient):
    conversation_id = str(uuid4())
    response = await hr_client.post(
        "/query",
        json={
            "question": "Câu hỏi mới sau khi bấm New Chat",
            "user_id": HR_USER_ID,
            "conversation_id": conversation_id,
            "conversation_title": "Câu hỏi mới sau khi bấm New Chat",
        },
    )
    assert response.status_code == 200
    done = next(event for event in parse_sse(response.text) if event.get("done"))

    conversations = (await hr_client.get("/conversations")).json()["conversations"]
    assert [item["id"] for item in conversations] == [conversation_id]

    detail = (await hr_client.get(f"/conversations/{conversation_id}")).json()
    assert detail["id"] == conversation_id
    assistant = next(message for message in detail["messages"] if message["role"] == "assistant")
    assert assistant["session_id"] == done["session_id"]
