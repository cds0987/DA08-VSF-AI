"""
MCP tool loader using langchain-mcp-adapters.

Discovers tool schemas from the MCP server at startup (or lazily on first
use) and caches the descriptions. Provides per-request ACL-wrapped
LangChain StructuredTool objects suitable for `model.bind_tools()` in the
LangGraph think_node.

Execution is delegated to the existing MCPToolClient (MCPStreamableHttpClient
or MockMCPClient) so this component does not maintain a persistent MCP
connection — it only needs a transient connection for schema discovery.
"""

import json
import logging
from dataclasses import asdict
from typing import Any, Literal

from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel, Field

from app.application.ports import MCPToolClient
from app.application.tools import ACL_WHITELIST
from app.infrastructure.config import Settings

logger = logging.getLogger(__name__)

_DEFAULT_RAG_DESC = (
    "Search internal company documents, policies, and procedures. "
    "Returns relevant text chunks ranked by relevance score."
)
_DEFAULT_HR_DESC = (
    "Query the authenticated user's personal HR data: "
    "remaining leave balance, leave request history, or payroll information. "
    "NOTE: user identity is injected automatically — do not pass user_id."
)


class _RagSearchInput(BaseModel):
    query: str = Field(description="Search query in Vietnamese or English")
    top_k: int = Field(default=5, ge=1, le=5, description="Number of results (max 5)")


class _HrQueryInput(BaseModel):
    intent: Literal["leave_balance", "leave_requests", "payroll"] = Field(
        description="HR data type: leave_balance | leave_requests | payroll"
    )


def _build_client_config(settings: Settings) -> dict[str, Any]:
    base = settings.mcp_service_url.rstrip("/")
    if not base.endswith("/mcp"):
        base = f"{base}/mcp"
    conn: dict[str, Any] = {"transport": "streamable_http", "url": base}
    token = (settings.mcp_internal_token or "").strip()
    if token:
        conn["headers"] = {"X-Internal-Token": token}
    return {"vinsmart": conn}


class LangChainMCPToolsLoader:
    """
    Lazy-loading bridge between langchain-mcp-adapters and the LangGraph agent.

    Usage:
        loader = LangChainMCPToolsLoader(settings, mcp_client)
        await loader.warmup()                     # call once at startup
        tools = await loader.get_acl_tools(...)   # per-request
    """

    def __init__(self, settings: Settings, mcp_client: MCPToolClient) -> None:
        self._mcp_client = mcp_client
        self._client_config = _build_client_config(settings)
        # name → description from MCP server; None = not yet fetched
        self._descriptions: dict[str, str] | None = None

    async def warmup(self) -> None:
        """
        Connect to MCP server, discover tool descriptions, then close.
        Swallows errors so a down mcp-service never blocks app startup.
        """
        try:
            async with MultiServerMCPClient(self._client_config) as client:
                raw_tools: list[BaseTool] = client.get_tools()
            self._descriptions = {t.name: t.description for t in raw_tools}
            logger.info(
                "mcp_tools_discovered",
                extra={"tools": list(self._descriptions)},
            )
        except Exception as exc:
            logger.warning("mcp_tools_warmup_failed (fallback to defaults): %s", exc)
            self._descriptions = {}

    async def get_acl_tools(
        self,
        user_id: str,
        allowed_doc_ids: frozenset[str],
    ) -> list[BaseTool]:
        """
        Return per-request ACL-guarded StructuredTools.

        Descriptions come from the MCP server (auto-discovered).
        Execution is delegated to self._mcp_client with backend-injected
        user_id and document_ids — the LLM cannot override these values.
        """
        if self._descriptions is None:
            await self.warmup()

        descriptions: dict[str, str] = self._descriptions or {}
        tools: list[BaseTool] = []

        if "rag_search" in ACL_WHITELIST:
            tools.append(
                self._make_rag_search(
                    description=descriptions.get("rag_search", _DEFAULT_RAG_DESC),
                    allowed_doc_ids=allowed_doc_ids,
                )
            )

        if "hr_query" in ACL_WHITELIST:
            tools.append(
                self._make_hr_query(
                    description=descriptions.get("hr_query", _DEFAULT_HR_DESC),
                    user_id=user_id,
                )
            )

        return tools

    async def reset(self) -> None:
        """Invalidate cached descriptions (e.g. after mcp-service redeploy)."""
        self._descriptions = None

    # ------------------------------------------------------------------
    # Private factory methods (one per whitelisted tool)
    # ------------------------------------------------------------------

    def _make_rag_search(
        self,
        description: str,
        allowed_doc_ids: frozenset[str],
    ) -> StructuredTool:
        client = self._mcp_client
        _doc_ids = allowed_doc_ids

        async def _rag_search(query: str, top_k: int = 5) -> str:
            results = await client.rag_search(
                query=query,
                document_ids=list(_doc_ids),
                top_k=min(top_k, 5),
            )
            return json.dumps({
                "results": [
                    {
                        "chunk_id": r.chunk_id,
                        "document_id": r.document_id,
                        "document_name": r.document_name,
                        "caption": r.caption,
                        "parent_text": r.parent_text,
                        "heading_path": r.heading_path,
                        "score": r.score,
                        "source_gcs_uri": r.source_gcs_uri,
                    }
                    for r in results
                ],
            })

        return StructuredTool.from_function(
            coroutine=_rag_search,
            name="rag_search",
            description=description,
            args_schema=_RagSearchInput,
        )

    def _make_hr_query(self, description: str, user_id: str) -> StructuredTool:
        client = self._mcp_client
        _uid = user_id

        async def _hr_query(
            intent: Literal["leave_balance", "leave_requests", "payroll"],
        ) -> str:
            result = await client.hr_query(user_id=_uid, intent=intent)
            return result.summary

        return StructuredTool.from_function(
            coroutine=_hr_query,
            name="hr_query",
            description=description,
            args_schema=_HrQueryInput,
        )
