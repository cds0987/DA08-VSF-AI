from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from app.core.config import McpSettings
from app.core.models import SearchHit
from app.core.search import SearchService, build_search_service
from app.tools.base import register_tool

logger = logging.getLogger("mcp-service")


def _hit_to_dict(hit: SearchHit) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk_id,
        "document_id": hit.document_id,
        "document_name": hit.document_name,
        "caption": hit.caption,
        "child_text": hit.child_text,
        "parent_text": hit.parent_text,
        "heading_path": hit.heading_path,
        "score": hit.score,
        "page_number": hit.page_number,
        "source_gcs_uri": hit.source_gcs_uri,
        "markdown_gcs_uri": hit.markdown_gcs_uri,
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class RagSearchConfig:
    rag_worker_url: str
    search_timeout_seconds: float
    rerank_impl: str
    rerank_model: str
    rerank_base_url: str
    rerank_api_key: str
    rerank_timeout_seconds: float
    rerank_batch_size: int
    rerank_passage_chars: int
    top_k_candidates: int
    rerank_top_k: int
    rerank_threshold: float

    @classmethod
    def from_params(cls, settings: McpSettings, params: Mapping[str, Any]) -> "RagSearchConfig":
        search = _mapping(params.get("search"))
        reranker = _mapping(params.get("reranker"))
        reranker_params = _mapping(reranker.get("params"))
        retrieval = _mapping(params.get("retrieval"))

        def _int(value: Any, default: int) -> int:
            text = str(value or "").strip()
            return int(text) if text else default

        def _float(value: Any, default: float) -> float:
            text = str(value or "").strip()
            return float(text) if text else default

        return cls(
            rag_worker_url=str(search.get("rag_worker_url") or settings.rag_worker_url).strip(),
            search_timeout_seconds=_float(
                search.get("timeout_seconds"), settings.search_timeout_seconds
            ),
            rerank_impl=str(reranker.get("impl") or settings.rerank_impl).strip().lower(),
            rerank_model=str(reranker.get("model") or settings.rerank_model).strip(),
            rerank_base_url=str(reranker.get("base_url") or settings.rerank_base_url).strip(),
            rerank_api_key=str(reranker.get("api_key") or settings.rerank_api_key).strip(),
            rerank_timeout_seconds=_float(
                reranker.get("timeout_seconds"), settings.rerank_timeout_seconds
            ),
            rerank_batch_size=_int(
                reranker_params.get("batch_size"), settings.rerank_batch_size
            ),
            rerank_passage_chars=_int(
                reranker_params.get("passage_chars"), settings.rerank_passage_chars
            ),
            top_k_candidates=_int(retrieval.get("top_k_candidates"), settings.top_k_candidates),
            rerank_top_k=_int(retrieval.get("rerank_top_k"), settings.rerank_top_k),
            rerank_threshold=_float(retrieval.get("rerank_threshold"), settings.rerank_threshold),
        )

    def to_settings(self, settings: McpSettings) -> McpSettings:
        return replace(
            settings,
            rag_worker_url=self.rag_worker_url,
            search_timeout_seconds=self.search_timeout_seconds,
            rerank_impl=self.rerank_impl,
            rerank_model=self.rerank_model,
            rerank_base_url=self.rerank_base_url,
            rerank_api_key=self.rerank_api_key,
            rerank_timeout_seconds=self.rerank_timeout_seconds,
            rerank_batch_size=self.rerank_batch_size,
            rerank_passage_chars=self.rerank_passage_chars,
            top_k_candidates=self.top_k_candidates,
            rerank_top_k=self.rerank_top_k,
            rerank_threshold=self.rerank_threshold,
        )


class RagSearchTool:
    name = "rag_search"

    def __init__(self, settings: McpSettings, params: Mapping[str, Any]) -> None:
        self._settings = RagSearchConfig.from_params(settings, params).to_settings(settings)
        self._service: SearchService = build_search_service(self._settings)

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
        # mcp KHÔNG còn sở hữu embed model/collection contract (đã chuyển sang
        # rag-worker). Startup chỉ log — verify contract/stamp diễn ra phía rag-worker.
        logger.info(
            "mcp_tool_verify_ok tool=%s rag_worker_url=%s",
            self.name,
            self._settings.rag_worker_url,
        )

    async def aclose(self) -> None:
        await self._service.aclose()


register_tool("rag_search", lambda settings, params: RagSearchTool(settings, params))
