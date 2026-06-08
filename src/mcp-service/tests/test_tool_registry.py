from __future__ import annotations

import asyncio

import pytest

from app.core.config import McpSettings
from app.tools.base import available_tools, register_tool, resolve_tool


class FakeTool:
    name = "fake_tool"

    def __init__(self, settings: McpSettings, params: dict) -> None:
        self.settings = settings
        self.params = params
        self.registered_with = None
        self.verified = False
        self.closed = False

    def register(self, mcp) -> None:
        self.registered_with = mcp

    async def verify(self) -> None:
        self.verified = True

    async def aclose(self) -> None:
        self.closed = True


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


def test_register_and_resolve_fake_tool() -> None:
    register_tool("fake_registry_tool", lambda settings, params: FakeTool(settings, dict(params)), override=True)

    tool = resolve_tool(
        "fake_registry_tool",
        settings=_settings(),
        params={"answer": 42},
    )

    assert isinstance(tool, FakeTool)
    assert tool.params == {"answer": 42}
    assert "fake_registry_tool" in available_tools()
    asyncio.run(tool.verify())
    asyncio.run(tool.aclose())
    assert tool.verified is True
    assert tool.closed is True


def test_register_duplicate_name_requires_override() -> None:
    register_tool("duplicate_registry_tool", lambda settings, params: FakeTool(settings, dict(params)), override=True)

    with pytest.raises(ValueError):
        register_tool("duplicate_registry_tool", lambda settings, params: FakeTool(settings, dict(params)))


def test_entry_point_tool_disabled_without_explicit_enable(monkeypatch) -> None:
    """Tool đến từ entry-point bên thứ ba KHÔNG tự bật khi config không khai
    `enabled`; built-in thì vẫn bật mặc định."""
    from app.interfaces import mcp_server

    register_tool(
        "external_probe_tool",
        lambda settings, params: FakeTool(settings, dict(params)),
        override=True,
    )

    settings = _settings()
    # available_tools chỉ trả tool ta quan tâm để cô lập test khỏi tool thật.
    monkeypatch.setattr(mcp_server, "available_tools", lambda: ["external_probe_tool"])
    monkeypatch.setattr(
        mcp_server, "is_entry_point_tool", lambda name: name == "external_probe_tool"
    )
    monkeypatch.setattr(
        type(settings), "tool_spec", lambda self, name: __import__(
            "app.core.config", fromlist=["ToolSpec"]
        ).ToolSpec(enabled=True, enabled_explicit=False, params={}),
    )

    # Không có tool nào bật -> build_mcp raise (entry-point tool bị bỏ qua).
    with pytest.raises(RuntimeError, match="no MCP tool enabled"):
        mcp_server.build_mcp(settings)
