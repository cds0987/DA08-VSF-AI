from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.config import McpSettings
from app.core.search import SearchService, build_search_service
from app.core.vectorstore import SearchHit
from app.tools.base import register_tool


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


class RagSearchTool:
    name = "rag_search"

    def __init__(self, settings: McpSettings, params: Mapping[str, Any]) -> None:
        del params
        self._service: SearchService = build_search_service(settings)

    def register(self, mcp: Any) -> None:
        service = self._service

        @mcp.tool()
        async def rag_search(
            query: str,
            document_ids: list[str] | None = None,
            top_k: int | None = None,
        ) -> dict[str, Any]:
            """Search internal chunks, scoped by document_ids when provided."""

            hits = await service.rag_search(query, document_ids=document_ids, top_k=top_k)
            return {"results": [_hit_to_dict(hit) for hit in hits]}

    async def verify(self) -> None:
        await self._service.verify_contract()

    async def aclose(self) -> None:
        await self._service.aclose()


register_tool("rag_search", lambda settings, params: RagSearchTool(settings, params))
