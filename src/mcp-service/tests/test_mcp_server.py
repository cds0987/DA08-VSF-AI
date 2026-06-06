from __future__ import annotations

import asyncio
import sys
import types

from app.core.config import McpSettings
from app.core.vectorstore import SearchHit
from app.interfaces.mcp_server import build_mcp, mcp_endpoint_url


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

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator

    def run(self, *, transport: str) -> None:
        self.transport = transport


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
