from __future__ import annotations

import asyncio
import json
import sys
import types

from app.core.config import McpSettings
from app.core.vectorstore import SearchHit
from app.interfaces.mcp_server import (
    MCP_INTERNAL_TOKEN_HEADER,
    InternalTokenAuthMiddleware,
    build_mcp,
    build_mcp_middleware,
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


def _settings() -> McpSettings:
    return McpSettings(
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

    fake_mcp_module = types.ModuleType("mcp")
    fake_server_module = types.ModuleType("mcp.server")
    fake_fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp_module.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp_module)
    monkeypatch.setattr("app.interfaces.mcp_server.build_search_service", lambda settings: stub_service)
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_PORT", "8003")

    mcp, service = build_mcp(_settings())

    assert service is stub_service
    assert mcp.host == "0.0.0.0"
    assert mcp.port == 8003
    assert mcp.stateless_http is True
    assert mcp.json_response is True
    assert "rag_search" in mcp.tools

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


def test_build_mcp_middleware_enabled_when_internal_token_is_configured(monkeypatch) -> None:
    monkeypatch.setenv("MCP_INTERNAL_TOKEN", "secret")

    middleware = build_mcp_middleware()

    assert len(middleware) == 1
    assert middleware[0].cls is InternalTokenAuthMiddleware
    assert middleware[0].kwargs["token"] == "secret"


def test_build_mcp_middleware_disabled_without_internal_token(monkeypatch) -> None:
    monkeypatch.delenv("MCP_INTERNAL_TOKEN", raising=False)

    assert build_mcp_middleware() == []


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
