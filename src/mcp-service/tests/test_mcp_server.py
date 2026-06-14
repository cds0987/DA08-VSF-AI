from __future__ import annotations

import asyncio
import json
import sys
import types

import httpx

from app.core.config import McpSettings
from app.core.vectorstore import SearchHit
from app.interfaces.mcp_server import (
    MCP_INTERNAL_TOKEN_HEADER,
    InternalTokenAuthMiddleware,
    build_mcp,
    build_mcp_middleware,
    enforce_production_auth,
    mcp_endpoint_url,
)


class FakeFastMCP:
    def __init__(
        self,
        name: str,
        *,
        host: str,
        port: int,
        stateless_http: bool,
        json_response: bool,
    ) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.stateless_http = stateless_http
        self.json_response = json_response
        self.tools: dict[str, object] = {}
        self.transport: str | None = None
        self.run_kwargs: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator

    def run(self, *, transport: str, **kwargs) -> None:
        self.transport = transport
        self.run_kwargs = kwargs


class StubService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def rag_search(self, query: str, document_ids=None, top_k=None):
        self.calls.append({"query": query, "document_ids": document_ids, "top_k": top_k})
        return [
            SearchHit(
                chunk_id="chunk-1",
                document_id="doc-1",
                document_name="Doc 1.pdf",
                caption="Leave policy",
                parent_text="Annual leave is 12 days.",
                heading_path=["Benefits"],
                score=0.92,
                page_number=1,
                source_gcs_uri="gs://bucket/doc-1.pdf",
                markdown_gcs_uri="gs://bucket/doc-1.md",
            )
        ]


class FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None, url: str = "http://hr-service:8004/hr/query") -> None:
        self.status_code = status_code
        self._json_body = json_body or {}
        self.request = httpx.Request("POST", url)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=self.request, json=self._json_body)
            raise httpx.HTTPStatusError("error", request=self.request, response=response)

    def json(self) -> dict:
        return self._json_body


class FakeAsyncClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []
        self.post_response = FakeResponse(
            200,
            {
                "intent": "leave_balance",
                "data": {
                    "annual_total": 12,
                    "annual_used": 4,
                    "annual_remaining": 8,
                    "sick_total": 10,
                    "sick_used": 1,
                    "sick_remaining": 9,
                },
                "summary": "ban con 8 ngay phep nam va 9 ngay phep om.",
            },
        )
        self.get_response = FakeResponse(200, {"status": "ok"}, url="http://hr-service:8004/health")

    async def post(self, path: str, json=None, headers=None):
        self.calls.append(("POST", path, json, headers))
        return self.post_response

    async def get(self, path: str, headers=None):
        self.calls.append(("GET", path, None, headers))
        return self.get_response

    async def aclose(self) -> None:
        return None


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
    )


async def _empty_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _run_auth_middleware(headers: list[tuple[bytes, bytes]]):
    messages: list[dict] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(message):
        messages.append(message)

    middleware = InternalTokenAuthMiddleware(app, token="secret")
    scope = {"type": "http", "headers": headers, "method": "POST", "path": "/mcp"}
    await middleware(scope, _empty_receive, send)
    return messages


def test_mcp_endpoint_url_uses_streamable_http_path() -> None:
    assert mcp_endpoint_url("mcp-service", 8003) == "http://mcp-service:8003/mcp"


def test_build_mcp_registers_rag_search_tool_and_query_service_shape(monkeypatch) -> None:
    stub_service = StubService()
    built_with: list[McpSettings] = []

    fake_mcp_module = types.ModuleType("mcp")
    fake_server_module = types.ModuleType("mcp.server")
    fake_fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp_module.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp_module)
    monkeypatch.setattr(
        "app.tools.rag_search.build_search_service",
        lambda settings: built_with.append(settings) or stub_service,
    )

    settings = McpSettings(
        **{
            **_settings().__dict__,
            "tools_profile": {
                "rag_search": {
                    "embedder": {
                        "base_url": "https://embed.example",
                        "api_key": "embed-key",
                        "dimension": "1024",
                    },
                    "vector_store": {
                        "impl": "qdrant",
                        "params": {
                            "collection": "team_docs",
                            "url": "https://qdrant.example",
                            "api_key": "vector-key",
                            "timeout": "15",
                        },
                    },
                    "vectorstore_contract": {
                        "provider": "qdrant",
                        "collection": "team_docs",
                        "embed_model": "text-embedding-3-large",
                    },
                    "reranker": {
                        "impl": "llm",
                        "model": "rerank-model",
                        "base_url": "https://rerank.example",
                        "api_key": "rerank-key",
                        "timeout_seconds": "45",
                        "params": {
                            "batch_size": "4",
                            "passage_chars": "600",
                        },
                    },
                    "retrieval": {
                        "top_k_candidates": "12",
                        "rerank_top_k": "5",
                        "rerank_threshold": "0.4",
                    },
                },
                "hr_query": {"enabled": "0"},
            },
        }
    )

    mcp, tools = build_mcp(settings)

    rag_tool = next(tool for tool in tools if tool.name == "rag_search")
    assert rag_tool.name == "rag_search"
    assert mcp.host == "0.0.0.0"
    assert mcp.port == 8003
    assert mcp.stateless_http is True
    assert mcp.json_response is True
    assert "rag_search" in mcp.tools
    assert built_with[0].collection == "team_docs"
    assert built_with[0].embed_model == "text-embedding-3-large"
    assert built_with[0].dimension == 1024
    assert built_with[0].url == "https://qdrant.example"
    assert built_with[0].embed_base_url == "https://embed.example"
    assert built_with[0].rerank_impl == "llm"
    assert built_with[0].top_k_candidates == 12
    assert built_with[0].rerank_top_k == 5
    assert built_with[0].rerank_threshold == 0.4

    result = asyncio.run(mcp.tools["rag_search"]("leave policy", ["doc-1"], None))

    assert stub_service.calls == [{"query": "leave policy", "document_ids": ["doc-1"], "top_k": None}]
    assert result == {
        "results": [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "document_name": "Doc 1.pdf",
                "caption": "Leave policy",
                "parent_text": "Annual leave is 12 days.",
                "heading_path": ["Benefits"],
                "score": 0.92,
                "page_number": 1,
                "source_gcs_uri": "gs://bucket/doc-1.pdf",
                "markdown_gcs_uri": "gs://bucket/doc-1.md",
            }
        ]
    }


def test_build_mcp_registers_hr_query_tool(monkeypatch) -> None:
    fake_mcp_module = types.ModuleType("mcp")
    fake_server_module = types.ModuleType("mcp.server")
    fake_fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp_module.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp_module)

    import app.tools.hr_query as hr_module
    from tests.test_hr_query_tool import USER_HR

    fake_client = FakeAsyncClient()
    monkeypatch.setattr(hr_module.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

    settings = McpSettings(
        **{
            **_settings().__dict__,
            "tools_profile": {
                "rag_search": {"enabled": "0"},
                "leave_write": {"enabled": "0"},
                "hr_query": {
                    "enabled": "1",
                    "params": {
                        "hr_service_url": "http://hr-service:8004",
                        "internal_token": "test-token",
                    },
                },
            },
        }
    )

    mcp, tools = build_mcp(settings)

    assert [tool.name for tool in tools] == ["hr_query"]
    assert "hr_query" in mcp.tools
    assert "rag_search" not in mcp.tools

    # Tool LLM-facing chỉ nhận user_id -> POST /hr/profile (passthrough fake payload).
    result = asyncio.run(mcp.tools["hr_query"](USER_HR))

    assert result["data"]["annual_remaining"] == 8
    assert set(result.keys()) == {"intent", "data", "summary"}
    assert fake_client.calls[0] == (
        "POST",
        "/hr/profile",
        {"user_id": USER_HR},
        {"X-Internal-Token": "test-token"},
    )


def test_build_mcp_registers_both_tools_simultaneously(monkeypatch) -> None:
    """Cả rag_search và hr_query bật cùng lúc — không tool nào ẩn tool kia."""
    stub_service = StubService()

    fake_mcp_module = types.ModuleType("mcp")
    fake_server_module = types.ModuleType("mcp.server")
    fake_fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp_module.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp_module)
    monkeypatch.setattr(
        "app.tools.rag_search.build_search_service",
        lambda settings: stub_service,
    )

    import app.tools.hr_query as hr_module
    from tests.test_hr_query_tool import USER_HR

    fake_client = FakeAsyncClient()
    monkeypatch.setattr(hr_module.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

    settings = McpSettings(
        **{
            **_settings().__dict__,
            "tools_profile": {
                "rag_search": {
                    "embedder": {
                        "base_url": "https://embed.example",
                        "api_key": "embed-key",
                        "dimension": "1024",
                    },
                    "vector_store": {
                        "impl": "qdrant",
                        "params": {
                            "collection": "team_docs",
                            "url": "https://qdrant.example",
                            "api_key": "vector-key",
                            "timeout": "15",
                        },
                    },
                    "vectorstore_contract": {
                        "provider": "qdrant",
                        "collection": "team_docs",
                        "embed_model": "text-embedding-3-large",
                    },
                    "reranker": {"impl": "none"},
                    "retrieval": {
                        "top_k_candidates": "10",
                        "rerank_top_k": "3",
                        "rerank_threshold": "0.5",
                    },
                },
                "hr_query": {
                    "enabled": "1",
                    "params": {
                        "hr_service_url": "http://hr-service:8004",
                        "internal_token": "test-token",
                    },
                },
            },
        }
    )

    mcp, tools = build_mcp(settings)

    tool_names = {tool.name for tool in tools}
    assert "rag_search" in tool_names
    assert "hr_query" in tool_names
    assert "rag_search" in mcp.tools
    assert "hr_query" in mcp.tools

    hr_result = asyncio.run(mcp.tools["hr_query"](USER_HR))
    assert hr_result["data"]["annual_remaining"] == 8

    rag_result = asyncio.run(mcp.tools["rag_search"]("leave policy", None, None))
    assert rag_result["results"][0]["document_id"] == "doc-1"


def test_build_mcp_middleware_enabled_when_internal_token_is_configured() -> None:
    middleware = build_mcp_middleware("secret")

    assert len(middleware) == 1
    assert middleware[0].cls is InternalTokenAuthMiddleware
    assert middleware[0].kwargs["token"] == "secret"


def test_build_mcp_middleware_disabled_without_internal_token() -> None:
    assert build_mcp_middleware("") == []
    assert build_mcp_middleware("   ") == []


def test_internal_token_auth_middleware_rejects_missing_or_invalid_header() -> None:
    missing = asyncio.run(_run_auth_middleware([]))
    invalid = asyncio.run(_run_auth_middleware([(MCP_INTERNAL_TOKEN_HEADER.lower().encode("ascii"), b"wrong")]))

    assert missing[0]["status"] == 401
    assert json.loads(missing[1]["body"]) == {"detail": "Not authenticated"}
    assert invalid[0]["status"] == 401


def test_internal_token_auth_middleware_accepts_valid_header() -> None:
    messages = asyncio.run(
        _run_auth_middleware([(MCP_INTERNAL_TOKEN_HEADER.lower().encode("ascii"), b"secret")])
    )

    assert messages[0]["status"] == 200
    assert messages[1]["body"] == b"ok"


# ─────────────────────── T6: fail-closed production auth ───────────────────────

import dataclasses  # noqa: E402

import pytest  # noqa: E402


def test_enforce_production_auth_raises_when_token_missing_in_prod() -> None:
    settings = dataclasses.replace(_settings(), app_env="production", internal_token="")
    with pytest.raises(RuntimeError, match="fail-open"):
        enforce_production_auth(settings)


def test_enforce_production_auth_ok_when_token_set_in_prod() -> None:
    settings = dataclasses.replace(_settings(), app_env="production", internal_token="secret")
    enforce_production_auth(settings)  # không raise


def test_enforce_production_auth_allows_fail_open_in_dev() -> None:
    settings = dataclasses.replace(_settings(), app_env="development", internal_token="")
    enforce_production_auth(settings)  # dev được phép tắt auth


def test_enforce_production_auth_prod_alias() -> None:
    settings = dataclasses.replace(_settings(), app_env="prod", internal_token="")
    with pytest.raises(RuntimeError):
        enforce_production_auth(settings)

