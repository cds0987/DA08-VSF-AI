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
        rag_worker_url="http://rag-worker:8000",
        search_timeout_seconds=30.0,
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


def test_tool_returns_full_profile(monkeypatch) -> None:
    # Tool LLM-facing: CHỈ nhận user_id -> POST /hr/profile -> trả toàn bộ hồ sơ.
    payload = {
        "intent": "profile",
        "data": {
            "leave_balance": {"annual_remaining": 8, "sick_remaining": 9},
            "payroll": [{"period": "2026-06", "net_salary": 1000.0}],
            "attendance": {"period": "2026-06", "work_days": 20, "late_count": 1},
        },
        "summary": "Hồ sơ HR cá nhân.",
    }
    _, fn, client = _tool(monkeypatch, post_response=FakeResponse(200, payload))

    result = asyncio.run(fn(USER_HR))

    assert result == payload
    assert client.calls[0][0] == "POST"
    assert client.calls[0][1] == "/hr/profile"
    assert client.calls[0][2] == {"user_id": USER_HR}
    assert client.calls[0][3] == {"X-Internal-Token": "test-token"}


def test_profile_soft_404(monkeypatch) -> None:
    _, fn, _ = _tool(monkeypatch, post_response=FakeResponse(404, {"detail": "no HR data"}))

    result = asyncio.run(fn(USER_HR))

    assert result["intent"] == "profile"
    assert result["data"] == {}


def test_profile_raises_on_http_error(monkeypatch) -> None:
    _, fn, _ = _tool(monkeypatch, post_response=FakeResponse(503, {"detail": "down"}))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fn(USER_HR))


def test_profile_logs_masked_user_id(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    import app.tools.hr_query as hr_module

    _, fn, _ = _tool(monkeypatch, post_response=FakeResponse(200, {"intent": "profile", "data": {}, "summary": "ok"}))
    masked_user = hr_module._mask_user_id(USER_HR)

    with caplog.at_level("INFO", logger="mcp-service"):
        asyncio.run(fn(USER_HR))

    assert "hr_query profile" in caplog.text
    assert masked_user in caplog.text
    assert USER_HR not in caplog.text


# ── Granular _call (giữ backward-compat; tool LLM dùng profile) ──────────────
def test_call_leave_balance_shape_and_headers(monkeypatch) -> None:
    payload = {
        "intent": "leave_balance",
        "data": {"annual_remaining": 8, "sick_remaining": 9},
        "summary": "Bạn còn 8 ngày phép năm và 9 ngày phép ốm.",
    }
    tool, _, client = _tool(monkeypatch, post_response=FakeResponse(200, payload))

    result = asyncio.run(tool._call(USER_HR, "leave_balance"))

    assert result == payload
    assert client.calls[0][1] == "/hr/query"
    assert client.calls[0][2] == {"user_id": USER_HR, "intent": "leave_balance"}


def test_call_rejects_unknown_intent(monkeypatch) -> None:
    tool, _, client = _tool(monkeypatch)

    result = asyncio.run(tool._call(USER_HR, "recruitment"))

    assert result == {
        "intent": "recruitment",
        "data": {},
        "summary": "Intent 'recruitment' chưa được hỗ trợ.",
    }
    assert client.calls == []


def test_call_soft_404(monkeypatch) -> None:
    tool, _, _ = _tool(monkeypatch, post_response=FakeResponse(404, {"detail": "no HR data"}))

    result = asyncio.run(tool._call(USER_HR, "leave_balance"))

    assert result["intent"] == "leave_balance"
    assert result["data"] == {}
    assert result["summary"] == "Bạn chưa có dữ liệu HR cho mục này."


def test_verify_hits_health_endpoint(monkeypatch) -> None:
    tool, _, client = _tool(monkeypatch)

    asyncio.run(tool.verify())

    assert client.calls[0][0] == "GET"
    assert client.calls[0][1] == "/health"
    assert client.calls[0][3] == {"X-Internal-Token": "test-token"}


def test_verify_degraded_does_not_raise(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    # hr-service /health trả 503 -> verify KHÔNG được raise (best-effort), chỉ warning.
    tool, _, _ = _tool(monkeypatch, get_response=FakeResponse(503, {"detail": "down"}, url="http://hr-service:8004/health"))

    with caplog.at_level("WARNING", logger="mcp-service"):
        asyncio.run(tool.verify())  # phải không ném

    assert "hr_query verify degraded" in caplog.text


def test_aclose_closes_client(monkeypatch) -> None:
    tool, _, client = _tool(monkeypatch)

    asyncio.run(tool.verify())
    asyncio.run(tool.aclose())

    assert client.closed is True
