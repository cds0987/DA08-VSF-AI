import httpx
import pytest

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.external import mcp_client as mcp_module
from app.infrastructure.external.mcp_client import MCPJsonRpcClient
from app.interfaces.api.dependencies import get_mcp_client


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeAsyncClient:
    calls: list[dict] = []

    def __init__(self, *, timeout: int) -> None:
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url: str, json: dict):
        self.__class__.calls.append({"url": url, "json": json, "timeout": self.timeout})
        method = json["method"]
        if method == "tools/list":
            return FakeResponse(
                {
                    "result": {
                        "tools": [
                            {"name": "rag_search"},
                            {"name": "hr_query"},
                        ]
                    }
                }
            )
        if json["params"]["name"] == "rag_search":
            return FakeResponse(
                {
                    "result": {
                        "content": [
                            {
                                "type": "json",
                                "json": {
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
                                            "source_s3_uri": "s3://docs/policy.pdf",
                                            "markdown_s3_uri": "s3://docs/policy.md",
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                }
            )
        return FakeResponse(
            {
                "result": {
                    "content": [
                        {
                            "type": "json",
                            "json": {
                                "intent": "payroll",
                                "payroll": [
                                    {
                                        "period": "2026-05",
                                        "gross_salary": 30000000,
                                        "deductions": 2800000,
                                        "net_salary": 27200000,
                                    }
                                ],
                                "summary": "Payroll summary",
                            },
                        }
                    ]
                }
            }
        )


@pytest.mark.asyncio
async def test_mcp_json_rpc_client_calls_tools_and_maps_results(monkeypatch):
    FakeAsyncClient.calls = []
    monkeypatch.setattr(mcp_module.httpx, "AsyncClient", FakeAsyncClient)
    client = MCPJsonRpcClient(
        Settings(_env_file=None, mcp_service_url="http://mcp-service:8003", mcp_timeout_seconds=7)
    )

    tools = await client.list_tools()
    rag_results = await client.rag_search("policy question", ["doc-1"], top_k=3)
    hr_result = await client.hr_query("user-1", "payroll")

    assert tools == ["rag_search", "hr_query"]
    assert FakeAsyncClient.calls[0]["url"] == "http://mcp-service:8003/mcp"
    assert FakeAsyncClient.calls[1]["json"]["params"]["arguments"] == {
        "query": "policy question",
        "document_ids": ["doc-1"],
        "top_k": 3,
    }
    assert rag_results[0].chunk_id == "chunk-1"
    assert rag_results[0].score == 0.91
    assert FakeAsyncClient.calls[2]["json"]["params"]["arguments"] == {
        "user_id": "user-1",
        "intent": "payroll",
    }
    assert hr_result.intent == "payroll"
    assert hr_result.summary == "Payroll summary"


def test_dependencies_select_mcp_json_rpc_client_when_mcp_mode_is_mcp(monkeypatch):
    monkeypatch.setenv("MCP_MODE", "mcp")
    get_settings.cache_clear()
    get_mcp_client.cache_clear()

    client = get_mcp_client()

    assert isinstance(client, MCPJsonRpcClient)
