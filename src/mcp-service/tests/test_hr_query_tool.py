from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.config import McpSettings

USER_HR = "11111111-1111-4111-8111-111111111111"
USER_FINANCE = "22222222-2222-4222-8222-222222222222"


class FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None, url: str = "http://hr-service:8004/hr/query") -> None:
        self.status_code = status_code
        self._json_body = json_body or {}
        self.request = httpx.Request("POST", url)
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=self.request, json=self._json_body)
            raise httpx.HTTPStatusError("error", request=self.request, response=response)

    def json(self) -> dict:
        return self._json_body


class FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []
        self.post_response = FakeResponse(200)
        self.get_response = FakeResponse(200, {"status": "ok"}, url="http://hr-service:8004/health")
        self.closed = False

    async def post(self, path: str, json=None, headers=None):
        self.calls.append(("POST", path, json, headers))
        return self.post_response

    async def get(self, path: str, headers=None):
        self.calls.append(("GET", path, None, headers))
        return self.get_response

    async def aclose(self) -> None:
        self.closed = True


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def _settings() -> McpSettings:
    return McpSettings(
        host="0.0.0.0",
        port=8003,
        log_level="INFO",
        app_env="development",
        internal_token="",
        provider="qdrant",
        collection="rag_chatbot",
        embed_model="offline",
        dimension=256,
        url="",
        api_key="",
        embed_base_url="",
        embed_api_key="",
        rerank_impl="none",
        rerank_model="gpt-4o-mini",
        rerank_base_url="",
        rerank_api_key="",
        rerank_timeout_seconds=30.0,
        rerank_batch_size=8,
        rerank_passage_chars=800,
        top_k_candidates=20,
        rerank_top_k=3,
        rerank_threshold=0.6,
        options={},
        tools_profile={
            "hr_query": {
                "enabled": "1",
                "params": {
                    "hr_service_url": "http://hr-service:8004",
                    "internal_token": "test-token",
                },
            }
        },
    )


def _tool(monkeypatch, *, post_response: FakeResponse | None = None, get_response: FakeResponse | None = None):
    import app.tools.hr_query as hr_module

    fake_client = FakeAsyncClient()
    if post_response is not None:
        fake_client.post_response = post_response
    if get_response is not None:
        fake_client.get_response = get_response
    monkeypatch.setattr(hr_module.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

    params = {
        "params": {
            "hr_service_url": "http://hr-service:8004",
            "internal_token": "test-token",
        }
    }
    tool = hr_module.HrQueryTool(_settings(), params)
    mcp = FakeMCP()
    tool.register(mcp)
    return tool, mcp.tools["hr_query"], fake_client


def test_proxy_leave_balance_shape_and_headers(monkeypatch) -> None:
    payload = {
        "intent": "leave_balance",
        "data": {
            "annual_total": 12,
            "annual_used": 4,
            "annual_remaining": 8,
            "sick_total": 10,
            "sick_used": 1,
            "sick_remaining": 9,
        },
        "summary": "Bạn còn 8 ngày phép năm và 9 ngày phép ốm.",
    }
    _, fn, client = _tool(monkeypatch, post_response=FakeResponse(200, payload))

    result = asyncio.run(fn(USER_HR, "leave_balance"))

    assert result == payload
    assert client.calls[0][0] == "POST"
    assert client.calls[0][1] == "/hr/query"
    assert client.calls[0][2] == {"user_id": USER_HR, "intent": "leave_balance"}
    assert client.calls[0][3] == {"X-Internal-Token": "test-token"}


def test_proxy_leave_requests(monkeypatch) -> None:
    payload = {
        "intent": "leave_requests",
        "data": {
            "requests": [
                {
                    "leave_type": "annual",
                    "start_date": "2026-06-10",
                    "end_date": "2026-06-11",
                    "days_count": 2,
                    "status": "approved",
                }
            ]
        },
        "summary": "Đơn nghỉ gần nhất là annual từ 2026-06-10 đến 2026-06-11, trạng thái approved.",
    }
    _, fn, _ = _tool(monkeypatch, post_response=FakeResponse(200, payload))

    result = asyncio.run(fn(USER_HR, "leave_requests"))

    assert result["intent"] == "leave_requests"
    assert result["data"]["requests"][0]["leave_type"] == "annual"
    assert set(result.keys()) == {"intent", "data", "summary"}


def test_proxy_attendance(monkeypatch) -> None:
    payload = {
        "intent": "attendance",
        "data": {"period": "2026-06", "work_days": 20, "late_count": 1, "absent_count": 0},
        "summary": "Tháng này bạn có 20 ngày công, đi muộn 1 lần và vắng 0 ngày.",
    }
    _, fn, _ = _tool(monkeypatch, post_response=FakeResponse(200, payload))

    result = asyncio.run(fn(USER_HR, "attendance"))

    assert result["data"]["work_days"] == 20
    assert set(result.keys()) == {"intent", "data", "summary"}


def test_proxy_onboarding(monkeypatch) -> None:
    payload = {
        "intent": "onboarding",
        "data": {
            "status": "completed",
            "checklist": [{"task": "Nhat laptop va the", "done": True}],
            "completed_count": 1,
            "total_count": 1,
        },
        "summary": "Trạng thái onboarding: completed, đã hoàn thành 1/1 mục.",
    }
    _, fn, _ = _tool(monkeypatch, post_response=FakeResponse(200, payload))

    result = asyncio.run(fn(USER_HR, "onboarding"))

    assert result["data"]["status"] == "completed"
    assert set(result.keys()) == {"intent", "data", "summary"}


def test_proxy_raises_on_http_error(monkeypatch) -> None:
    _, fn, _ = _tool(monkeypatch, post_response=FakeResponse(503, {"detail": "down"}))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fn(USER_HR, "leave_balance"))


def test_verify_hits_health_endpoint(monkeypatch) -> None:
    tool, _, client = _tool(monkeypatch)

    asyncio.run(tool.verify())

    assert client.calls[0][0] == "GET"
    assert client.calls[0][1] == "/health"
    assert client.calls[0][3] == {"X-Internal-Token": "test-token"}


def test_aclose_closes_client(monkeypatch) -> None:
    tool, _, client = _tool(monkeypatch)

    asyncio.run(tool.verify())
    asyncio.run(tool.aclose())

    assert client.closed is True
