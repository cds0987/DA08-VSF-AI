from types import SimpleNamespace

import httpx
import pytest

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.external import mcp_client as mcp_module
from app.infrastructure.external.mcp_client import MCPStreamableHttpClient
from app.interfaces.api.dependencies import get_mcp_client


class FakeHttpClient:
    instances: list["FakeHttpClient"] = []

    def __init__(self, *, timeout: int, headers: dict | None = None) -> None:
        self.timeout = timeout
        self.headers = headers or {}
        self.closed = False
        self.__class__.instances.append(self)

    async def aclose(self) -> None:
        self.closed = True


class FakeTransportContext:
    calls: list[dict] = []

    def __init__(self, url: str, *, http_client: FakeHttpClient) -> None:
        self.url = url
        self.http_client = http_client

    async def __aenter__(self):
        self.__class__.calls.append({"url": self.url, "http_client": self.http_client})
        return "read-stream", "write-stream", lambda: "session-id"

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeClientSession:
    instances: list["FakeClientSession"] = []

    def __init__(self, read_stream, write_stream) -> None:
        self.read_stream = read_stream
        self.write_stream = write_stream
        self.initialized = False
        self.tool_calls: list[dict] = []
        self.__class__.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(name="rag_search"),
            ]
        )

    async def call_tool(self, name: str, arguments: dict):
        self.tool_calls.append({"name": name, "arguments": arguments})
        return SimpleNamespace(
            structuredContent={
                "results": [
                    {
                        "chunk_id": "chunk-1",
                        "document_id": "doc-1",
                        "document_name": "Policy.pdf",
                        "caption": "Policy",
                        "parent_text": "Policy text",
                        "heading_path": ["Policy"],
                        "score": 0.91,
                        "page_number": 1,
                        "source_gcs_uri": "gs://docs/policy.pdf",
                        "markdown_gcs_uri": "gs://docs/policy.md",
                    }
                ]
            },
            content=[],
            isError=False,
        )


def fake_streamable_http_client(url: str, *, http_client):
    return FakeTransportContext(url, http_client=http_client)


@pytest.mark.asyncio
async def test_mcp_streamable_client_uses_sdk_session_and_maps_results(monkeypatch):
    FakeHttpClient.instances = []
    FakeTransportContext.calls = []
    FakeClientSession.instances = []
    monkeypatch.setattr(mcp_module.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(mcp_module, "streamable_http_client", fake_streamable_http_client)
    monkeypatch.setattr(mcp_module, "ClientSession", FakeClientSession)
    client = MCPStreamableHttpClient(
        Settings(_env_file=None, mcp_service_url="http://mcp-service:8003", mcp_timeout_seconds=7)
    )

    tools = await client.list_tools()
    rag_results = await client.rag_search("policy question", ["doc-1"], top_k=3)

    assert tools == ["rag_search"]
    assert FakeTransportContext.calls[0]["url"] == "http://mcp-service:8003/mcp"
    assert FakeHttpClient.instances[0].timeout == 7
    assert FakeHttpClient.instances[0].headers == {}
    assert FakeClientSession.instances[0].initialized is True
    assert FakeClientSession.instances[1].tool_calls == [
        {
            "name": "rag_search",
            "arguments": {
                "query": "policy question",
                "document_ids": ["doc-1"],
                "top_k": 3,
            },
        }
    ]
    assert rag_results[0].chunk_id == "chunk-1"
    assert rag_results[0].parent_text == "Policy text"
    assert rag_results[0].source_gcs_uri == "gs://docs/policy.pdf"
    assert rag_results[0].markdown_gcs_uri == "gs://docs/policy.md"


@pytest.mark.asyncio
async def test_mcp_streamable_client_sends_internal_token_header_when_configured(monkeypatch):
    FakeHttpClient.instances = []
    FakeTransportContext.calls = []
    FakeClientSession.instances = []
    monkeypatch.setattr(mcp_module.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(mcp_module, "streamable_http_client", fake_streamable_http_client)
    monkeypatch.setattr(mcp_module, "ClientSession", FakeClientSession)
    client = MCPStreamableHttpClient(
        Settings(
            _env_file=None,
            mcp_service_url="http://mcp-service:8003",
            mcp_timeout_seconds=7,
            mcp_internal_token="secret-token",
        )
    )

    await client.list_tools()

    assert FakeHttpClient.instances[0].headers == {"X-Internal-Token": "secret-token"}


def test_dependencies_select_streamable_client_for_real_and_legacy_mcp_modes(monkeypatch):
    for mode in ("real", "mcp"):
        monkeypatch.setenv("MCP_MODE", mode)
        get_settings.cache_clear()
        get_mcp_client.cache_clear()

        client = get_mcp_client()

        assert isinstance(client, MCPStreamableHttpClient)


def test_raw_json_rpc_without_required_accept_header_is_not_used_anymore():
    request = httpx.Request("POST", "http://mcp-service:8003/mcp", json={"jsonrpc": "2.0"})

    assert "accept" not in request.headers or "text/event-stream" not in request.headers["accept"]
    assert not hasattr(mcp_module, "MCPJsonRpcClient")
