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
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel, Field

from app.application.ports import MCPToolClient, ToolSpec
from app.infrastructure.config import Settings

logger = logging.getLogger(__name__)

_DEFAULT_RAG_DESC = (
    "Search internal company documents, policies, and procedures. "
    "Returns relevant text chunks ranked by relevance score."
)
_DEFAULT_HR_DESC = (
    "Query the authenticated user's personal HR data: remaining leave balance, "
    "leave request history, attendance (work days / late / absent), onboarding "
    "progress, payroll, benefits, or performance review. "
    "NOTE: user identity is injected automatically — do not pass user_id."
)

class _RagSearchInput(BaseModel):
    query: str = Field(description="Search query in Vietnamese or English")
    top_k: int = Field(default=5, ge=1, le=10, description="Number of results (max 10)")


class _HrQueryInput(BaseModel):
    # KHÔNG field: hr_query trả toàn bộ hồ sơ HR, model không cần (và không được) điền gì.
    # user_id tiêm server-side ở act_node.
    pass


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
            # langchain-mcp-adapters >=0.2: MultiServerMCPClient is no longer an
            # async context manager and get_tools() is a coroutine that opens its
            # own transient session per call — must be awaited, not used via
            # `async with`. The old 0.1.0 form silently returned a coroutine
            # object here, making every warmup fall through to the except branch.
            client = MultiServerMCPClient(self._client_config)
            raw_tools: list[BaseTool] = await client.get_tools()
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
    ) -> list[BaseTool | dict]:
        """
        Return per-request ACL-guarded tools for model.bind_tools().

        Tool list is built dynamically from list_tool_specs() so a new tool
        added to mcp-service is automatically discovered — no code change needed.

        Routing rules:
          • rag_search  → bespoke StructuredTool (ACL doc_ids, score filter, sources)
          • hr_query    → bespoke StructuredTool (inject user_id, typed schema)
          • any other   → generic dict schema  (call_tool + summary-style in act_node)
        """
        specs: list[ToolSpec] = await self._mcp_client.list_tool_specs()

        # Rebuild description cache from freshly discovered specs.
        self._descriptions = {s.name: s.description for s in specs}

        tools: list[BaseTool | dict] = []
        for spec in specs:
            if spec.name == "rag_search":
                tools.append(
                    self._make_rag_search(
                        description=spec.description or _DEFAULT_RAG_DESC,
                        allowed_doc_ids=allowed_doc_ids,
                    )
                )
            elif spec.name == "hr_query":
                # hr_query no-arg: trả toàn bộ hồ sơ HR (user_id tiêm ở act_node).
                # Model gọi hr_query() rỗng = hợp lệ -> hết bug "intent rỗng".
                tools.append(
                    self._make_hr_query(
                        description=spec.description or _DEFAULT_HR_DESC,
                        user_id=user_id,
                    )
                )
            else:
                # Tool khác: discover động từ spec mcp (dict schema).
                tools.append(self._make_generic_tool(spec))

        # Fallback: mcp-service không trả spec nào (mcp down) -> ít nhất giữ rag_search
        # để agent không rỗng tool. hr_query bỏ qua: không có spec từ mcp thì không
        # hardcode schema intent ở đây (mcp down thì hr_query cũng không gọi được).
        if not tools:
            logger.warning("mcp_tools_empty_fallback: no specs returned, dùng rag_search + hr_query mặc định")
            tools.append(self._make_rag_search(_DEFAULT_RAG_DESC, allowed_doc_ids))
            tools.append(self._make_hr_query(_DEFAULT_HR_DESC, user_id))

        return tools

    async def reset(self) -> None:
        """Invalidate cached descriptions (e.g. after mcp-service redeploy)."""
        self._descriptions = None

    # ------------------------------------------------------------------
    # Private factory methods
    # ------------------------------------------------------------------

    def _make_generic_tool(self, spec: ToolSpec) -> dict:
        """
        Build an OpenAI function-tool schema dict for any non-rag, non-hr tool.

        Returns a plain dict — the OpenAIResponsesChatModel adapter passes it
        through _bind_tools_schema verbatim so the model sees the correct schema.
        Execution is handled by act_node via mcp_client.call_tool() (summary-style).

        NOTE: reserved params (user_id, document_ids, top_k) are already stripped
        from spec.input_schema by MCPStreamableHttpClient._strip_reserved_params().
        user_id is re-injected at execution time in act_node.
        """
        return {
            "type": "function",
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.input_schema or {"type": "object", "properties": {}},
        }

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
                top_k=min(top_k, 10),
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

        # KHÔNG tham số: model gọi hr_query() -> lấy toàn bộ profile (user_id tiêm
        # server-side). Hết failure mode "intent rỗng".
        async def _hr_query() -> str:
            raw = await client.call_tool("hr_query", {"user_id": _uid})
            payload = raw.get("data", raw) if isinstance(raw, dict) else raw
            return json.dumps(payload, ensure_ascii=False)

        return StructuredTool.from_function(
            coroutine=_hr_query,
            name="hr_query",
            description=description,
            args_schema=_HrQueryInput,
        )

