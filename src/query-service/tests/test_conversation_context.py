from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import HR_USER_ID


@pytest.mark.asyncio
async def test_context_and_summary_are_isolated_by_conversation():
    from app.interfaces.api.dependencies import get_conversation_repo

    repo = get_conversation_repo()
    first_id = str(uuid4())
    second_id = str(uuid4())
    await repo.save_message(HR_USER_ID, "user", "First chat context", conversation_id=first_id)
    await repo.save_message(HR_USER_ID, "user", "Second chat context", conversation_id=second_id)
    await repo.update_summary(HR_USER_ID, "First summary", conversation_id=first_id)

    first = await repo.get_context(HR_USER_ID, conversation_id=first_id)
    second = await repo.get_context(HR_USER_ID, conversation_id=second_id)

    assert [message.content for message in first.recent_messages] == ["First chat context"]
    assert first.summary == "First summary"
    assert [message.content for message in second.recent_messages] == ["Second chat context"]
    assert second.summary is None


@pytest.mark.asyncio
async def test_rename_rejects_blank_title(hr_client: AsyncClient):
    from app.interfaces.api.dependencies import get_conversation_repo

    conversation_id = str(uuid4())
    repo = get_conversation_repo()
    await repo.save_message(
        HR_USER_ID,
        "user",
        "Conversation with a title",
        conversation_id=conversation_id,
    )

    response = await hr_client.patch(
        f"/conversations/{conversation_id}",
        json={"title": "   "},
    )
    assert response.status_code == 422
