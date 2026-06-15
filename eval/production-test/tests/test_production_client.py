from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.auth import AuthSession
from lib.config import Settings
from lib.production_client import ProductionClient, parse_sse_packet


def settings(timeout: float = 30) -> Settings:
    return Settings(
        prod_base_url="https://prod.example",
        prod_api_base_url="https://prod.example",
        prod_email="user@example.com",
        prod_password="pw",
        prod_access_token=None,
        prod_refresh_token=None,
        user_service_path="/api/user",
        query_service_path="/api/query",
        document_service_path="/api/documents",
        mcp_url=None,
        mcp_internal_token=None,
        gateway_basic_auth=None,
        dataset_root=Path("eval/dataset"),
        dataset="dataset_new",
        output_root=Path("out"),
        question_timeout_seconds=timeout,
        concurrency=1,
        limit=1,
        limit_is_explicit=True,
        question_offset=0,
        include_doc_ids=(),
        exclude_doc_ids=(),
        questions_per_doc=None,
        dry_run=False,
    )


def test_parse_sse_packet() -> None:
    assert parse_sse_packet('data: {"token":"hi"}') == {"token": "hi"}
    assert parse_sse_packet(": keepalive") is None
    assert parse_sse_packet("data: not-json") is None


@pytest.mark.asyncio
async def test_sse_query_captures_answer_and_done() -> None:
    body = (
        'data: {"token":"Hello"}\n\n'
        'data: {"token":" world"}\n\n'
        'data: {"done":true,"session_id":"s1","trace_id":"t1","outcome":5,'
        '"sources":[{"document_name":"Doc","caption":"Cap","document_id":"d1"}]}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh"})
        if request.url.path.endswith("/auth/me"):
            return httpx.Response(200, json={"id": "u1", "email": "user@example.com", "role": "user", "account_type": "internal", "department": "HR"})
        if request.url.path.endswith("/query"):
            return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(404)

    cfg = settings()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = AuthSession(cfg, http)
        await auth.login()
        client = ProductionClient(cfg, http, auth)
        result = await client.query_with_recovery("question", trace_session="ts", conversation_title="ct")

    assert result.answer == "Hello world"
    assert result.done["session_id"] == "s1"
    assert result.sources[0]["document_id"] == "d1"
    assert result.first_token_latency_seconds is not None


@pytest.mark.asyncio
async def test_query_401_refreshes_and_replays() -> None:
    query_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal query_calls
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "access1", "refresh_token": "refresh1"})
        if request.url.path.endswith("/auth/me"):
            return httpx.Response(200, json={"id": "u1", "email": "user@example.com", "role": "user", "account_type": "internal", "department": "HR"})
        if request.url.path.endswith("/auth/refresh"):
            return httpx.Response(200, json={"access_token": "access2", "refresh_token": "refresh2"})
        if request.url.path.endswith("/query"):
            query_calls += 1
            if query_calls == 1:
                return httpx.Response(401, json={"detail": "expired"})
            return httpx.Response(200, content='data: {"token":"ok"}\n\ndata: {"done":true,"session_id":"s"}\n\n')
        return httpx.Response(404)

    cfg = settings()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = AuthSession(cfg, http)
        await auth.login()
        client = ProductionClient(cfg, http, auth)
        result = await client.query_with_recovery("question", trace_session="ts", conversation_title="ct")

    assert result.answer == "ok"
    assert result.retry_count == 1
    assert result.auth_recovered is True
    assert auth.stats.refresh_count == 1


@pytest.mark.asyncio
async def test_question_timeout_marks_result() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh"})
        if request.url.path.endswith("/auth/me"):
            return httpx.Response(200, json={"id": "u1", "email": "user@example.com", "role": "user", "account_type": "internal", "department": "HR"})
        if request.url.path.endswith("/query"):
            await asyncio.sleep(0.05)
            return httpx.Response(200, content='data: {"token":"late"}\n\n')
        return httpx.Response(404)

    cfg = settings(timeout=0.01)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = AuthSession(cfg, http)
        await auth.login()
        client = ProductionClient(cfg, http, auth)
        result = await client.query_with_recovery("question", trace_session="ts", conversation_title="ct")

    assert result.timed_out is True
    assert "timed out" in result.error
