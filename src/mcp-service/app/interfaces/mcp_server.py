"""Expose rag_search over MCP Streamable HTTP."""

from __future__ import annotations

import hmac
import os
from typing import Any, List, Optional

from app.core.config import McpSettings, load_settings
from app.core.search import SearchService, build_search_service
from app.core.vectorstore import SearchHit

MCP_DEFAULT_HOST = "0.0.0.0"
MCP_DEFAULT_PORT = 8003
MCP_PATH = "/mcp"
MCP_INTERNAL_TOKEN_ENV = "MCP_INTERNAL_TOKEN"
MCP_INTERNAL_TOKEN_HEADER = "X-Internal-Token"


def mcp_endpoint_url(host: str, port: int) -> str:
    return f"http://{host}:{port}{MCP_PATH}"


def _hit_to_dict(hit: SearchHit) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk_id,
        "document_id": hit.document_id,
        "document_name": hit.document_name,
        "caption": hit.caption,
        "parent_text": hit.parent_text,
        "heading_path": hit.heading_path,
        "score": hit.score,
        "page_number": hit.page_number,
        "source_gcs_uri": hit.source_gcs_uri,
        "markdown_gcs_uri": hit.markdown_gcs_uri,
    }


def _configured_internal_token() -> str:
    return (os.getenv(MCP_INTERNAL_TOKEN_ENV) or "").strip()


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


def build_mcp_middleware() -> list[Any]:
    token = _configured_internal_token()
    if not token:
        return []

    from starlette.middleware import Middleware

    return [Middleware(InternalTokenAuthMiddleware, token=token)]


def build_mcp(settings: McpSettings | None = None) -> tuple[Any, SearchService]:
    from mcp.server.fastmcp import FastMCP

    settings = settings or load_settings()
    service = build_search_service(settings)

    host = os.getenv("MCP_HOST", MCP_DEFAULT_HOST)
    port = int(os.getenv("MCP_PORT", str(MCP_DEFAULT_PORT)))
    mcp = FastMCP(
        "mcp-service",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool()
    async def rag_search(
        query: str,
        document_ids: Optional[List[str]] = None,
        top_k: Optional[int] = None,
    ) -> dict[str, Any]:
        """Search internal chunks, scoped by document_ids when provided."""

        hits = await service.rag_search(query, document_ids=document_ids, top_k=top_k)
        return {"results": [_hit_to_dict(hit) for hit in hits]}

    return mcp, service
