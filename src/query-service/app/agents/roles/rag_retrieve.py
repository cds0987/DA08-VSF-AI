"""Role rag_retrieve: lấy tài liệu nội bộ (rag_search) + (tùy chọn) phân tích theo direction.

Worker song song. Fetch chunks -> lọc theo threshold -> nếu có model: mini trích/phân tích
phần liên quan theo direction; không có model / mini lỗi -> trả raw chunks (vẫn dùng được).
"""
from __future__ import annotations

import json
import logging

from app.agents.base import AgentRole, WorkerInput, WorkerOutput
from app.agents.registry import register_agent
from app.agents.roles._llm import acomplete

logger = logging.getLogger(__name__)


@register_agent("rag_retrieve")
class RagRetrieveRole(AgentRole):
    name = "rag_retrieve"
    capability = "worker"
    tools = ("rag_search",)

    async def run(self, task: WorkerInput) -> WorkerOutput:
        ctx = self.ctx
        query = task.input if isinstance(task.input, str) else json.dumps(task.input, ensure_ascii=False)

        if not ctx.allowed_doc_ids:
            return WorkerOutput(task.step_id, self.name, "", status="no_info",
                                error="no document access")

        # Bước tool ra SSE: UI hiện "Tìm kiếm tài liệu" + query.
        if ctx.emit:
            await ctx.emit({"phase": "acting", "tool": "rag_search", "tool_args": {"query": query}})

        # Retry 1 lần (mcp rag_search intermittent) — giống act_node hiện tại.
        try:
            results = await self._search(query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("rag_retrieve_retry step=%s err=%s", task.step_id, str(exc)[:120])
            try:
                results = await self._search(query)
            except Exception as exc2:  # noqa: BLE001
                return WorkerOutput(task.step_id, self.name, "", status="error", error=str(exc2)[:200])

        threshold = ctx.rag_score_threshold
        qualified = [r for r in results if getattr(r, "score", 0) >= threshold]
        used = qualified or results  # dưới ngưỡng vẫn đưa context, chỉ không cite
        # Kết quả tool ra SSE: số tài liệu + tên (UI hiện bước observing).
        if ctx.emit:
            await ctx.emit({
                "phase": "observing", "tool": "rag_search",
                "tool_result_summary": {
                    "count": len(qualified),
                    "docs": sorted({r.document_name for r in qualified}),
                },
            })
        if not used:
            return WorkerOutput(task.step_id, self.name, "", status="no_info")

        chunks = [
            {
                "document_name": r.document_name,
                "caption": r.caption,
                "parent_text": r.parent_text,
                "heading_path": r.heading_path,
                "page_number": r.page_number,
            }
            for r in used
        ]
        sources = [
            {
                "document_name": r.document_name,
                "caption": r.caption,
                "heading_path": r.heading_path,
                "score": r.score,
                "source_gcs_uri": r.source_gcs_uri,
                "document_id": r.document_id,
                "page_number": r.page_number,
                "chunk_id": r.chunk_id,
            }
            for r in qualified  # chỉ chunk đạt ngưỡng mới thành citation
        ]

        raw_text = json.dumps({"results": chunks}, ensure_ascii=False)

        # Phân tích theo direction bằng mini (nếu có model). Lỗi -> raw chunks.
        model = ctx.make_model(self.capability) if ctx.make_model else None
        analysis = await acomplete(
            model,
            system=(
                "Bạn là trợ lý trích xuất. Dựa CHỈ trên tài liệu cho sẵn, trả lời theo "
                "định hướng. Nêu rõ trích dẫn tài liệu. Không bịa."
            ),
            user=f"Định hướng: {task.direction or query}\n\nTài liệu:\n{raw_text}",
        )
        output = analysis or raw_text
        return WorkerOutput(task.step_id, self.name, output, sources=sources, status="ok",
                            retrieved=len(used))

    async def _search(self, query: str):
        return await self.ctx.mcp_client.rag_search(
            query=query,
            document_ids=list(self.ctx.allowed_doc_ids),
            top_k=self.ctx.rag_top_k,
        )
