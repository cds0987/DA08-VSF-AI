import json

import httpx
import jwt
import pytest

from app.application.tool_decision import ToolDecision
from app.infrastructure.auth import auth_service
from app.infrastructure.auth.auth_service import AuthService
from app.infrastructure.config import Settings, get_settings
from app.interfaces.api.dependencies import get_connection_manager, get_mcp_client, get_tool_decision_client
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


def done_event(response: httpx.Response) -> dict:
    done_lines = [line for line in response.text.splitlines() if '"done": true' in line]
    return json.loads(done_lines[-1].removeprefix("data: "))


def streamed_answer(response: httpx.Response) -> str:
    parts: list[str] = []
    for line in response.text.splitlines():
        if not line.startswith('data: {"token":'):
            continue
        event = json.loads(line.removeprefix("data: "))
        parts.append(event["token"])
    return "".join(parts)


class FakeUserServiceResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class FakeUserServiceClient:
    response = FakeUserServiceResponse(
        200,
        {
            "id": HR_USER_ID,
            "email": "hr.user@company.com",
            "role": "user",
            "department": "HR",
        },
    )
    last_base_url = None
    last_timeout = None
    last_get = None

    def __init__(self, *, base_url: str, timeout: float) -> None:
        self.__class__.last_base_url = base_url
        self.__class__.last_timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, path: str, *, headers: dict[str, str]):
        self.__class__.last_get = {"path": path, "headers": headers}
        return self.__class__.response


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
async def test_identity_question_bypasses_rag_and_returns_no_sources(client, tokens):
    mcp_client = get_mcp_client()
    mcp_client.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["admin"]),
        json={"question": "Bạn là ai?", "user_id": ADMIN_USER_ID},
    )

    assert response.status_code == 200
    assert "trợ lý nội bộ VinSmartFuture" in streamed_answer(response)
    done = done_event(response)
    assert done["sources"] == []
    assert not any(call.tool_name == "rag_search" for call in mcp_client.last_tool_calls)


@pytest.mark.asyncio
async def test_user_service_auth_mode_calls_auth_me(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "user_service")
    monkeypatch.setenv("USER_SERVICE_URL", "http://user-service.test")
    monkeypatch.setenv("AUTH_HTTP_TIMEOUT_SECONDS", "3")
    get_settings.cache_clear()
    FakeUserServiceClient.response = FakeUserServiceResponse(
        200,
        {
            "id": HR_USER_ID,
            "email": "hr.user@company.com",
            "role": "user",
            "department": "HR",
        },
    )
    monkeypatch.setattr(auth_service.httpx, "AsyncClient", FakeUserServiceClient)

    response = await client.post(
        "/query",
        headers=auth("real-access-token"),
        json={"question": "Chinh sach nghi phep la gi?", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    assert FakeUserServiceClient.last_base_url == "http://user-service.test"
    assert FakeUserServiceClient.last_timeout == 3.0
    assert FakeUserServiceClient.last_get == {
        "path": "/auth/me",
        "headers": {"Authorization": "Bearer real-access-token"},
    }


@pytest.mark.asyncio
async def test_user_service_auth_mode_maps_auth_failure_to_401(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "user_service")
    get_settings.cache_clear()
    FakeUserServiceClient.response = FakeUserServiceResponse(401, {"detail": "Not authenticated"})
    monkeypatch.setattr(auth_service.httpx, "AsyncClient", FakeUserServiceClient)

    response = await client.post(
        "/query",
        headers=auth("expired-token"),
        json={"question": "test", "user_id": HR_USER_ID},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_user_service_auth_mode_keeps_user_id_mismatch_forbidden(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "user_service")
    get_settings.cache_clear()
    FakeUserServiceClient.response = FakeUserServiceResponse(
        200,
        {
            "id": HR_USER_ID,
            "email": "hr.user@company.com",
            "role": "user",
            "department": "HR",
        },
    )
    monkeypatch.setattr(auth_service.httpx, "AsyncClient", FakeUserServiceClient)

    response = await client.post(
        "/query",
        headers=auth("real-access-token"),
        json={"question": "test", "user_id": FINANCE_USER_ID},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_jwt_auth_mode_decodes_user_service_claims():
    token = jwt.encode(
        {
            "sub": HR_USER_ID,
            "role": "user",
            "department": "HR",
            "jti": "token-id-1",
        },
        "shared-secret-with-at-least-32-bytes",
        algorithm="HS256",
    )
    settings = Settings(_env_file=None, auth_mode="jwt", jwt_secret_key="shared-secret-with-at-least-32-bytes")

    user = await AuthService(settings).authenticate(f"Bearer {token}")

    assert user.id == HR_USER_ID
    assert user.role == "user"
    assert user.department == "HR"


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
async def test_paraphrased_leave_balance_question_routes_to_hr_tool(client, tokens):
    mcp_client = get_mcp_client()
    mcp_client.reset()

    response = await client.post(
        "/query",
        headers=auth(tokens["finance"]),
        json={
            "question": "How much remaining leave do I still have?",
            "user_id": FINANCE_USER_ID,
        },
    )

    assert response.status_code == 200
    last_call = mcp_client.last_tool_calls[-1]
    assert last_call.tool_name == "hr_query"
    assert last_call.arguments == {
        "user_id": FINANCE_USER_ID,
        "intent": "leave_balance",
    }
    assert '"sources": []' in response.text


@pytest.mark.asyncio
async def test_valid_hr_tool_decision_ignores_llm_supplied_user_id(client, tokens):
    mcp_client = get_mcp_client()
    mcp_client.reset()
    decision_client = get_tool_decision_client()
    decision_client.force_next_decision(
        ToolDecision(
            tool_name="hr_query",
            arguments={
                "intent": "payroll",
                "user_id": ADMIN_USER_ID,
            },
        )
    )

    response = await client.post(
        "/query",
        headers=auth(tokens["finance"]),
        json={"question": "Cho tôi xem bảng lương tháng này", "user_id": FINANCE_USER_ID},
    )

    assert response.status_code == 200
    last_call = mcp_client.last_tool_calls[-1]
    assert last_call.tool_name == "hr_query"
    assert last_call.arguments == {
        "user_id": FINANCE_USER_ID,
        "intent": "payroll",
    }
    assert '"sources": []' in response.text


@pytest.mark.asyncio
async def test_rag_tool_decision_ignores_llm_supplied_acl_arguments(client, tokens):
    mcp_client = get_mcp_client()
    mcp_client.reset()
    decision_client = get_tool_decision_client()
    decision_client.force_next_decision(
        ToolDecision(
            tool_name="rag_search",
            arguments={
                "query": "Executive compensation",
                "document_ids": ["dddddddd-0004-4000-8000-000000000004"],
                "top_k": 99,
            },
        )
    )

    response = await client.post(
        "/query",
        headers=auth(tokens["finance"]),
        json={"question": "Finance report guideline", "user_id": FINANCE_USER_ID},
    )

    assert response.status_code == 200
    last_call = mcp_client.last_tool_calls[-1]
    assert last_call.tool_name == "rag_search"
    assert last_call.arguments["query"] == "Finance report guideline"
    assert last_call.arguments["top_k"] == 3
    assert "dddddddd-0003-4000-8000-000000000003" in last_call.arguments["document_ids"]
    assert "dddddddd-0004-4000-8000-000000000004" not in last_call.arguments["document_ids"]


@pytest.mark.asyncio
async def test_invalid_tool_decision_falls_back_to_rag_search(client, tokens):
    mcp_client = get_mcp_client()
    mcp_client.reset()
    decision_client = get_tool_decision_client()
    decision_client.force_next_decision(
        ToolDecision(
            tool_name="hr_query",
            arguments={"intent": "benefits"},
        )
    )

    response = await client.post(
        "/query",
        headers=auth(tokens["finance"]),
        json={"question": "Finance report guideline", "user_id": FINANCE_USER_ID},
    )

    assert response.status_code == 200
    last_call = mcp_client.last_tool_calls[-1]
    assert last_call.tool_name == "rag_search"
    assert last_call.arguments["document_ids"]


@pytest.mark.asyncio
async def test_unknown_tool_decision_falls_back_to_rag_search(client, tokens):
    mcp_client = get_mcp_client()
    mcp_client.reset()
    decision_client = get_tool_decision_client()
    decision_client.force_next_decision(
        ToolDecision(
            tool_name="delete_document",
            arguments={"document_ids": ["dddddddd-0004-4000-8000-000000000004"]},
        )
    )

    response = await client.post(
        "/query",
        headers=auth(tokens["finance"]),
        json={"question": "Finance report guideline", "user_id": FINANCE_USER_ID},
    )

    assert response.status_code == 200
    last_call = mcp_client.last_tool_calls[-1]
    assert last_call.tool_name == "rag_search"
    assert "dddddddd-0004-4000-8000-000000000004" not in last_call.arguments["document_ids"]


@pytest.mark.asyncio
async def test_fallback_for_low_score_query(client, tokens):
    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "hôm nay ăn gì?", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    done = done_event(response)
    assert done["sources"] == []
    assert done["fallback"] is True


@pytest.mark.asyncio
async def test_rag_query_returns_relevant_sources_without_top_secret_for_regular_user(client, tokens):
    response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Chính sách nghỉ phép là gì?", "user_id": HR_USER_ID},
    )

    assert response.status_code == 200
    done = done_event(response)
    source_names = [source["document_name"] for source in done["sources"]]
    assert "Chinh_sach_nghi_phep_2026.pdf" in source_names
    assert "Executive_Compensation_Top_Secret.pdf" not in source_names
    assert done["sources"][0]["source_gcs_uri"]
    assert "source_s3_uri" not in done["sources"][0]


@pytest.mark.asyncio
async def test_rag_cache_does_not_leak_admin_sources_to_regular_user(client, tokens):
    admin_response = await client.post(
        "/query",
        headers=auth(tokens["admin"]),
        json={"question": "Executive compensation", "user_id": ADMIN_USER_ID},
    )
    assert admin_response.status_code == 200
    admin_done = done_event(admin_response)
    assert any(
        source["document_name"] == "Executive_Compensation_Top_Secret.pdf"
        for source in admin_done["sources"]
    )

    user_response = await client.post(
        "/query",
        headers=auth(tokens["hr"]),
        json={"question": "Executive compensation", "user_id": HR_USER_ID},
    )

    assert user_response.status_code == 200
    user_done = done_event(user_response)
    assert all(
        source["document_name"] != "Executive_Compensation_Top_Secret.pdf"
        for source in user_done["sources"]
    )
    assert user_done["sources"] == []
    last_call = get_mcp_client().last_tool_calls[-1]
    assert last_call.tool_name == "rag_search"
    assert "dddddddd-0004-4000-8000-000000000004" not in last_call.arguments["document_ids"]


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
    await get_connection_manager().connect(auth_service.MOCK_TOKENS[tokens["hr"]])
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
async def test_notification_history_rejects_unbounded_limit(client, tokens):
    response = await client.get(
        "/notifications/history?limit=101",
        headers=auth(tokens["hr"]),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_dev_mock_notification_is_disabled_when_env_flag_false(client, tokens, monkeypatch):
    monkeypatch.setenv("ENABLE_DEV_ENDPOINTS", "false")
    get_settings.cache_clear()
    payload = {
        "doc_id": "dddddddd-0002-4000-8000-000000000002",
        "document_name": "Chinh_sach_nghi_phep_2026.pdf",
        "classification": "internal",
        "allowed_departments": [],
        "allowed_user_ids": [],
    }

    response = await client.post(
        "/dev/mock-notifications/doc-new",
        headers=auth(tokens["admin"]),
        json=payload,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_dev_mock_notification_requires_admin(client, tokens):
    await get_connection_manager().connect(auth_service.MOCK_TOKENS[tokens["hr"]])
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
