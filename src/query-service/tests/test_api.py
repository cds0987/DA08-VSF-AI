import json

import httpx
import pytest

from app.interfaces.api.main import app


HR_USER_ID = "11111111-1111-4111-8111-111111111111"
FINANCE_USER_ID = "22222222-2222-4222-8222-222222222222"
ADMIN_USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_query_sse_streams_token_and_done(client, tokens):
    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Chính sách nghỉ phép là gì?", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    body = response.text
    assert 'data: {"token":' in body
    assert '"done": true' in body
    assert '"session_id":' in body


@pytest.mark.asyncio
async def test_user_id_mismatch_is_forbidden(client, tokens):
    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "test", "user_id": FINANCE_USER_ID},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_hr_tool_injects_authenticated_user_id(client, tokens):
    response = await client.post(
        "/query",
        headers=auth(tokens["finance"]),
        json={"question": "Tôi còn bao nhiêu ngày nghỉ phép?", "user_id": FINANCE_USER_ID},
    )

    assert response.status_code == 200
    assert "27200000" not in response.text
    assert '"sources": []' in response.text


@pytest.mark.asyncio
async def test_fallback_for_low_score_query(client, tokens):
    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "alien không liên quan", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    assert '"token": "Không "' in response.text
    assert '"token": "tìm "' in response.text
    assert '"fallback": true' in response.text


@pytest.mark.asyncio
async def test_conversations_feedback_and_admin_metrics(client, tokens):
    query_response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Onboarding cần làm gì?", "user_id": HR_USER_ID},
    )
    done_lines = [line for line in query_response.text.splitlines() if '"done": true' in line]
    done = json.loads(done_lines[-1].removeprefix("data: "))
    session_id = done["session_id"]

    history = await client.get("/conversations", headers=auth(tokens["hr"]))
    assert history.status_code == 200
    assert len(history.json()["messages"]) == 2

    feedback = await client.post(
        "/feedback",
        headers=auth(tokens["hr"]),
        json={"session_id": session_id, "score": 1},
    )
    assert feedback.status_code == 200

    user_metrics = await client.get("/admin/metrics", headers=auth(tokens["hr"]))
    assert user_metrics.status_code == 403

    admin_metrics = await client.get("/admin/metrics", headers=auth(tokens["admin"]))
    assert admin_metrics.status_code == 200
    assert admin_metrics.json()["total_questions"] == 1
    assert admin_metrics.json()["feedback"]["up"] == 1


@pytest.mark.asyncio
async def test_feedback_score_validation(client, tokens):
    response = await client.post(
        "/feedback",
        headers=auth(tokens["hr"]),
        json={"session_id": "missing", "score": 0},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cors_allows_chat_and_admin_origins(client):
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }
    chat_response = await client.options("/query", headers=headers)
    assert chat_response.status_code == 200
    assert chat_response.headers["access-control-allow-origin"] == "http://localhost:3000"

    admin_headers = dict(headers)
    admin_headers["Origin"] = "http://localhost:3001"
    admin_response = await client.options("/admin/metrics", headers=admin_headers)
    assert admin_response.status_code == 200
    assert admin_response.headers["access-control-allow-origin"] == "http://localhost:3001"


@pytest.mark.asyncio
async def test_cors_rejects_unknown_origin(client):
    response = await client.options(
        "/query",
        headers={
            "Origin": "http://localhost:9999",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_notification_history_unread_and_mark_read(client, tokens):
    published = await client.post(
        "/dev/mock-notifications/doc-new",
        headers=auth(tokens["admin"]),
        json={
            "doc_id": "dddddddd-0002-4000-8000-000000000002",
            "document_name": "Chinh_sach_nghi_phep_2026.pdf",
            "classification": "internal",
            "allowed_departments": [],
            "allowed_user_ids": [],
        },
    )
    assert published.status_code == 200

    history = await client.get("/notifications/history", headers=auth(tokens["hr"]))
    assert history.status_code == 200
    item = history.json()["items"][0]
    assert item["is_read"] is False

    unread = await client.get("/notifications/unread-count", headers=auth(tokens["hr"]))
    assert unread.json()["unread"] == 1

    marked = await client.post(f"/notifications/{item['id']}/read", headers=auth(tokens["hr"]))
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True


@pytest.mark.asyncio
async def test_dev_mock_notification_requires_admin(client, tokens):
    payload = {
        "doc_id": "dddddddd-0002-4000-8000-000000000002",
        "document_name": "Chinh_sach_nghi_phep_2026.pdf",
        "classification": "internal",
        "allowed_departments": [],
        "allowed_user_ids": [],
    }

    missing_token = await client.post("/dev/mock-notifications/doc-new", json=payload)
    assert missing_token.status_code == 401

    regular_user = await client.post(
        "/dev/mock-notifications/doc-new",
        headers=auth(tokens["hr"]),
        json=payload,
    )
    assert regular_user.status_code == 403

    admin = await client.post(
        "/dev/mock-notifications/doc-new",
        headers=auth(tokens["admin"]),
        json=payload,
    )
    assert admin.status_code == 200
    assert admin.json()["delivered"] >= 1
