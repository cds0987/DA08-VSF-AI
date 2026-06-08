from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from app.core.config import McpSettings
from app.core.search import SearchService, build_search_service
from app.core.vectorstore import SearchHit
from app.tools.base import register_tool

logger = logging.getLogger("mcp-service")


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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class RagSearchConfig:
    provider: str
    collection: str
    embed_model: str
    dimension: int
    url: str
    api_key: str
    basic_auth: str
    timeout: int | None
    embed_base_url: str
    embed_api_key: str
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
        embedder = _mapping(params.get("embedder"))
        vector_store = _mapping(params.get("vector_store"))
        vector_params = _mapping(vector_store.get("params"))
        contract = _mapping(params.get("vectorstore_contract"))
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
            provider=str(contract.get("provider") or vector_store.get("impl") or settings.provider).strip(),
            collection=str(contract.get("collection") or vector_params.get("collection") or settings.collection).strip(),
            embed_model=str(contract.get("embed_model") or settings.embed_model).strip(),
            dimension=_int(embedder.get("dimension"), settings.dimension),
            url=str(vector_params.get("url") or settings.url).strip(),
            api_key=str(vector_params.get("api_key") or settings.api_key).strip(),
            basic_auth=str(vector_params.get("basic_auth") or settings.basic_auth).strip(),
            timeout=(
                _int(vector_params.get("timeout"), settings.timeout)
                if str(vector_params.get("timeout") or "").strip()
                else settings.timeout
            ),
            embed_base_url=str(embedder.get("base_url") or settings.embed_base_url).strip(),
            embed_api_key=str(embedder.get("api_key") or settings.embed_api_key).strip(),
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
            provider=self.provider,
            collection=self.collection,
            embed_model=self.embed_model,
            dimension=self.dimension,
            url=self.url,
            api_key=self.api_key,
            basic_auth=self.basic_auth,
            timeout=self.timeout,
            embed_base_url=self.embed_base_url,
            embed_api_key=self.embed_api_key,
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
        contract = self._settings.contract()
        logger.info(
            "mcp_tool_verify_start tool=%s index=%s fingerprint=%s deployment=%s",
            self.name,
            contract.index_id,
            contract.fingerprint,
            self._settings.deployment,
        )
        await self._service.verify_contract()
        logger.info(
            "mcp_tool_verify_ok tool=%s index=%s fingerprint=%s",
            self.name,
            contract.index_id,
            contract.fingerprint,
        )

    async def aclose(self) -> None:
        await self._service.aclose()


register_tool("rag_search", lambda settings, params: RagSearchTool(settings, params))
