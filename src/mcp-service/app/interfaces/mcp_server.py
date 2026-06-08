"""Expose rag_search over MCP Streamable HTTP."""

from __future__ import annotations

import hmac
from typing import Any

from app.core.config import McpSettings, load_settings
import app.tools  # noqa: F401
from app.tools.base import McpTool, available_tools, resolve_tool

MCP_DEFAULT_HOST = "0.0.0.0"
MCP_DEFAULT_PORT = 8003
MCP_PATH = "/mcp"
MCP_INTERNAL_TOKEN_HEADER = "X-Internal-Token"


def mcp_endpoint_url(host: str, port: int) -> str:
    return f"http://{host}:{port}{MCP_PATH}"


class InternalTokenAuthMiddleware:
    def __init__(self, app, *, token: str, header_name: str = MCP_INTERNAL_TOKEN_HEADER) -> None:
        self.app = app
        self._token = token
        self._header_name = header_name.lower().encode("ascii")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        provided = None
        for key, value in scope.get("headers", []):
            if key.lower() == self._header_name:
                provided = value.decode("utf-8")
                break

        if provided is None or not hmac.compare_digest(provided, self._token):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"detail":"Not authenticated"}',
                }
            )
            return

        await self.app(scope, receive, send)


def build_mcp_middleware(token: str) -> list[Any]:
    token = (token or "").strip()
    if not token:
        return []

    from starlette.middleware import Middleware

    return [Middleware(InternalTokenAuthMiddleware, token=token)]


def build_mcp(settings: McpSettings | None = None) -> tuple[Any, list[McpTool]]:
    from mcp.server.fastmcp import FastMCP

    settings = settings or load_settings()

    mcp = FastMCP(
        "mcp-service",
        host=settings.host,
        port=settings.port,
        stateless_http=True,
        json_response=True,
    )
    tools: list[McpTool] = []
    for name in available_tools():
        spec = settings.tool_spec(name)
        if not spec.enabled:
            continue
        tool = resolve_tool(name, settings=settings, params=spec.params)
        tool.register(mcp)
        tools.append(tool)
    if not tools:
        raise RuntimeError("no MCP tool enabled")
    return mcp, tools
