"""MCP server — expose tool `rag_search` qua MCP (Streamable HTTP).

Import `mcp` SDK LAZY trong build_mcp để app/core/* vẫn import/test được khi chưa
cài SDK. Port chỉ là cổng cho query-service (MCP client); KHÔNG liên quan rag-worker.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional

from app.core.config import McpSettings, load_settings
from app.core.search import SearchService, build_search_service
from app.core.vectorstore import SearchHit


def _hit_to_dict(hit: SearchHit) -> dict[str, Any]:
    # Shape = contract SearchResult (docs/contracts.md): dùng *_gcs_uri.
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


def build_mcp(settings: McpSettings | None = None) -> tuple[Any, SearchService]:
    """Tạo FastMCP server + SearchService. Trả (mcp, service) để main verify rồi run."""
    from mcp.server.fastmcp import FastMCP

    settings = settings or load_settings()
    service = build_search_service(settings)

    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8003"))
    mcp = FastMCP("mcp-service", host=host, port=port)

    @mcp.tool()
    async def rag_search(
        query: str,
        document_ids: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Tìm chunk liên quan trong tài liệu nội bộ (đọc Qdrant, rerank top-k).

        document_ids do MCP client (query-service) inject sau khi lọc ACL.
        (mcp v1: document_ids hiện chưa lọc — xem TODO ACL trong search.py.)
        """
        hits = await service.rag_search(query, document_ids=document_ids, top_k=top_k)
        return [_hit_to_dict(hit) for hit in hits]

    return mcp, service
