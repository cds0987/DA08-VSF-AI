"""Tests for multi-conversation history APIs."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import FINANCE_USER_ID, HR_USER_ID, parse_sse


@pytest.mark.asyncio
async def test_get_conversations_empty(hr_client: AsyncClient):
    response = await hr_client.get("/conversations")
    assert response.status_code == 200
    assert response.json() == {"conversations": [], "messages": []}


@pytest.mark.asyncio
async def test_new_chats_remain_separate_after_history_reload(hr_client: AsyncClient):
    first_id = str(uuid4())
    second_id = str(uuid4())

    for conversation_id, question in (
        (first_id, "Câu hỏi trong chat thứ nhất"),
        (second_id, "Câu hỏi trong chat thứ hai"),
    ):
        response = await hr_client.post(
            "/query",
            json={
                "question": question,
                "user_id": HR_USER_ID,
                "conversation_id": conversation_id,
                "conversation_title": question,
            },
        )
        assert response.status_code == 200
        assert any(event.get("done") for event in parse_sse(response.text))

    history = await hr_client.get("/conversations")
    assert history.status_code == 200
    items = history.json()["conversations"]
    assert {item["id"] for item in items} == {first_id, second_id}
    assert history.json()["messages"]
    titles = {item["id"]: item["title"] for item in items}
    assert titles[first_id] == "Câu hỏi trong chat thứ nhất"
    assert titles[second_id] == "Câu hỏi trong chat thứ hai"

    first = await hr_client.get(f"/conversations/{first_id}")
    second = await hr_client.get(f"/conversations/{second_id}")
    assert first.status_code == 200
    assert second.status_code == 200
    assert any(
        message["content"] == "Câu hỏi trong chat thứ nhất"
        for message in first.json()["messages"]
    )
    assert not any(
        message["content"] == "Câu hỏi trong chat thứ hai"
        for message in first.json()["messages"]
    )
    assert any(
        message["content"] == "Câu hỏi trong chat thứ hai"
        for message in second.json()["messages"]
    )


@pytest.mark.asyncio
async def test_conversation_detail_preserves_assistant_session_id(hr_client: AsyncClient):
    conversation_id = str(uuid4())
    response = await hr_client.post(
        "/query",
        json={
            "question": "Kiểm tra session của câu trả lời",
            "user_id": HR_USER_ID,
            "conversation_id": conversation_id,
        },
    )
    done = next(event for event in parse_sse(response.text) if event.get("done"))

    detail = await hr_client.get(f"/conversations/{conversation_id}")
    assistant = next(
        message
        for message in detail.json()["messages"]
        if message["role"] == "assistant"
    )
    assert assistant["session_id"] == done["session_id"]
    assert "sources" in assistant


@pytest.mark.asyncio
async def test_rename_and_delete_one_conversation(hr_client: AsyncClient):
    from app.interfaces.api.dependencies import get_conversation_repo

    conversation_id = str(uuid4())
    repo = get_conversation_repo()
    await repo.save_message(
        HR_USER_ID,
        "user",
        "Original title",
        conversation_id=conversation_id,
    )

    renamed = await hr_client.patch(
        f"/conversations/{conversation_id}",
        json={"title": "Renamed chat"},
    )
    assert renamed.status_code == 200
    detail = await hr_client.get(f"/conversations/{conversation_id}")
    assert detail.json()["title"] == "Renamed chat"

    deleted = await hr_client.delete(f"/conversations/{conversation_id}")
    assert deleted.status_code == 200
    assert (await hr_client.get(f"/conversations/{conversation_id}")).status_code == 404


@pytest.mark.asyncio
async def test_conversations_are_isolated_per_user(
    hr_client: AsyncClient,
    finance_client: AsyncClient,
):
    from app.interfaces.api.dependencies import get_conversation_repo

    conversation_id = str(uuid4())
    repo = get_conversation_repo()
    await repo.save_message(
        HR_USER_ID,
        "user",
        "HR test message",
        conversation_id=conversation_id,
    )

    assert (await hr_client.get(f"/conversations/{conversation_id}")).status_code == 200
    assert (await finance_client.get(f"/conversations/{conversation_id}")).status_code == 404
    assert (
        await finance_client.patch(
            f"/conversations/{conversation_id}",
            json={"title": "Not allowed"},
        )
    ).status_code == 404
    assert (await finance_client.delete(f"/conversations/{conversation_id}")).status_code == 404


@pytest.mark.asyncio
async def test_clear_only_affects_own_history(
    hr_client: AsyncClient,
    finance_client: AsyncClient,
):
    from app.interfaces.api.dependencies import get_conversation_repo

    repo = get_conversation_repo()
    await repo.save_message(HR_USER_ID, "user", "HR message")
    await repo.save_message(FINANCE_USER_ID, "user", "Finance message")

    assert (await hr_client.delete("/conversations")).status_code == 200
    assert (await hr_client.get("/conversations")).json()["conversations"] == []
    assert len((await finance_client.get("/conversations")).json()["conversations"]) == 1


@pytest.mark.asyncio
async def test_legacy_query_without_conversation_id_uses_latest_chat(hr_client: AsyncClient):
    for question in ("Câu hỏi cũ 1", "Câu hỏi cũ 2"):
        response = await hr_client.post(
            "/query",
            json={"question": question, "user_id": HR_USER_ID},
        )
        assert response.status_code == 200

    items = (await hr_client.get("/conversations")).json()["conversations"]
    assert len(items) == 1
    detail = await hr_client.get(f"/conversations/{items[0]['id']}")
    user_messages = [
        message["content"]
        for message in detail.json()["messages"]
        if message["role"] == "user"
    ]
    assert user_messages == ["Câu hỏi cũ 1", "Câu hỏi cũ 2"]


@pytest.mark.asyncio
async def test_conversation_detail_returns_latest_messages(hr_client: AsyncClient):
    from app.interfaces.api.dependencies import get_conversation_repo

    conversation_id = str(uuid4())
    repo = get_conversation_repo()
    for index in range(505):
        await repo.save_message(
            HR_USER_ID,
            "user",
            f"message-{index}",
            conversation_id=conversation_id,
        )

    detail = await hr_client.get(f"/conversations/{conversation_id}")
    assert detail.status_code == 200
    messages = detail.json()["messages"]
    assert len(messages) == 500
    assert messages[0]["content"] == "message-5"
    assert messages[-1]["content"] == "message-504"


@pytest.mark.asyncio
async def test_deleted_conversation_is_not_recreated_by_late_assistant_save(
    hr_client: AsyncClient,
):
    from app.interfaces.api.dependencies import get_conversation_repo

    conversation_id = str(uuid4())
    repo = get_conversation_repo()
    await repo.save_message(
        HR_USER_ID,
        "user",
        "delete while streaming",
        conversation_id=conversation_id,
    )
    assert (await hr_client.delete(f"/conversations/{conversation_id}")).status_code == 200

    saved = await repo.save_message_detail(
        HR_USER_ID,
        "assistant",
        "late answer",
        conversation_id=conversation_id,
        create_if_missing=False,
    )

    assert saved is None
    assert (await hr_client.get(f"/conversations/{conversation_id}")).status_code == 404


@pytest.mark.asyncio
async def test_query_rejects_conversation_owned_by_another_user(
    hr_client: AsyncClient,
    finance_client: AsyncClient,
):
    from app.interfaces.api.dependencies import get_conversation_repo

    conversation_id = str(uuid4())
    repo = get_conversation_repo()
    await repo.save_message(
        HR_USER_ID,
        "user",
        "private HR chat",
        conversation_id=conversation_id,
    )

    response = await finance_client.post(
        "/query",
        json={
            "question": "try another user's chat",
            "user_id": FINANCE_USER_ID,
            "conversation_id": conversation_id,
        },
    )
    assert response.status_code == 403
