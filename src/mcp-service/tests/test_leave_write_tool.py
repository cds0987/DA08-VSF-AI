from __future__ import annotations

import asyncio

import httpx
import pytest

from tests.test_hr_query_tool import FakeMCP, _settings

USER = "11111111-1111-4111-8111-111111111111"


class FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}
        self.text = text
        self.request = httpx.Request("POST", "http://hr-service:8004/hr/leave-requests")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            resp = httpx.Response(self.status_code, request=self.request, json=self._json_body)
            raise httpx.HTTPStatusError("error", request=self.request, response=resp)

    def json(self) -> dict:
        return self._json_body


class FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[tuple] = []
        self.response = FakeResponse(201, {"id": "r1", "status": "pending", "approver_user_id": "m1"})
        self.get_response = FakeResponse(200, {"status": "ok"})
        self.closed = False

    async def request(self, method, path, json=None, headers=None):
        self.calls.append((method, path, json, headers))
        return self.response

    async def get(self, path, headers=None):
        self.calls.append(("GET", path, None, headers))
        return self.get_response

    async def aclose(self) -> None:
        self.closed = True


def _tool(monkeypatch, *, response: FakeResponse | None = None, get_response: FakeResponse | None = None):
    import app.tools.leave_write as mod

    fake = FakeClient()
    if response is not None:
        fake.response = response
    if get_response is not None:
        fake.get_response = get_response
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: fake)
    params = {"params": {"hr_service_url": "http://hr-service:8004", "internal_token": "tk"}}
    tool = mod.LeaveWriteTool(_settings(), params)
    mcp = FakeMCP()
    tool.register(mcp)
    return tool, mcp.tools, fake


def test_registers_three_functions(monkeypatch):
    _, tools, _ = _tool(monkeypatch)
    assert set(tools) == {"create_leave_request", "update_leave_request", "cancel_leave_request"}


def test_create_proxies_and_injects_user_id(monkeypatch):
    _, tools, fake = _tool(monkeypatch)
    out = asyncio.run(tools["create_leave_request"](
        USER, "annual", "2026-07-01", "2026-07-02", "nghỉ", "key-1"))
    assert out == {"id": "r1", "status": "pending", "approver_user_id": "m1"}
    method, path, body, headers = fake.calls[0]
    assert method == "POST" and path == "/hr/leave-requests"
    assert body["user_id"] == USER
    assert body["leave_type"] == "annual"
    assert body["idempotency_key"] == "key-1"
    assert headers == {"X-Internal-Token": "tk"}


def test_create_omits_empty_idempotency_key(monkeypatch):
    _, tools, fake = _tool(monkeypatch)
    asyncio.run(tools["create_leave_request"](USER, "sick", "2026-07-01", "2026-07-01"))
    body = fake.calls[0][2]
    assert "idempotency_key" not in body  # rỗng -> KHÔNG gửi (tránh đụng UNIQUE '')


def test_update_proxies_patch_with_request_id(monkeypatch):
    _, tools, fake = _tool(monkeypatch)
    asyncio.run(tools["update_leave_request"](
        USER, "req-9", "annual", "2026-08-01", "2026-08-02"))
    method, path, body, _ = fake.calls[0]
    assert method == "PATCH" and path == "/hr/leave-requests/req-9"
    assert body["user_id"] == USER


def test_cancel_proxies_post_cancel(monkeypatch):
    _, tools, fake = _tool(monkeypatch)
    asyncio.run(tools["cancel_leave_request"](USER, "req-9"))
    method, path, body, _ = fake.calls[0]
    assert method == "POST" and path == "/hr/leave-requests/req-9/cancel"
    assert body == {"user_id": USER}


def test_4xx_returns_structured_error_not_raise(monkeypatch):
    _, tools, _ = _tool(monkeypatch, response=FakeResponse(422, {"detail": "approver chưa cấu hình"}))
    out = asyncio.run(tools["create_leave_request"](USER, "annual", "2026-07-01", "2026-07-02"))
    assert out["ok"] is False
    assert out["status_code"] == 422
    assert "approver" in str(out["error"])


def test_5xx_raises(monkeypatch):
    _, tools, _ = _tool(monkeypatch, response=FakeResponse(503, {"detail": "down"}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(tools["create_leave_request"](USER, "annual", "2026-07-01", "2026-07-02"))


def test_verify_best_effort_when_hr_down(monkeypatch):
    tool, _, _ = _tool(monkeypatch, get_response=FakeResponse(500, {"detail": "down"}))
    # KHÔNG raise (best-effort) — không kéo sập rag_search.
    asyncio.run(tool.verify())
