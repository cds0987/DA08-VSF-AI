"""Unit: role-agent — fetch + fallback an toàn khi mini lỗi/không có model."""
from __future__ import annotations

from dataclasses import dataclass

from app.agents import roles  # noqa: F401 — register
from app.agents.base import RoleContext, WorkerInput
from app.agents.registry import AGENT_REGISTRY


@dataclass
class _Hit:
    document_name = "Quy dinh"
    caption = "c"
    parent_text = "Nghi phep 12 ngay"
    heading_path = ("A",)
    score = 0.8
    source_gcs_uri = "gs://x"
    document_id = "d1"
    page_number = 1
    chunk_id = "c1"


class _MockMCP:
    async def rag_search(self, query, document_ids, top_k):
        return [_Hit()]

    async def call_tool(self, name, args):
        return {"data": {"annual_remaining": 5}}


class _FakeModel:
    def __init__(self, text):
        self.text = text

    async def ainvoke(self, msgs):
        class R:
            pass
        r = R()
        r.content = self.text
        return r


def _ctx(model=None):
    return RoleContext(
        mcp_client=_MockMCP(), user_id="u1", allowed_doc_ids=("d1",),
        rag_top_k=5, rag_score_threshold=0.45,
        make_model=(lambda cap: model) if model else None,
    )


async def test_rag_retrieve_without_model_returns_raw_chunks():
    role = AGENT_REGISTRY.get("rag_retrieve")(_ctx())
    out = await role.run(WorkerInput(1, "rag_retrieve", "nghi phep", "trich"))
    assert out.status == "ok"
    assert len(out.sources) == 1
    assert out.retrieved == 1  # pipeline-health: chunk lấy được (kể cả dưới ngưỡng)
    assert "results" in out.output


async def test_rag_retrieve_with_model_analyzes():
    role = AGENT_REGISTRY.get("rag_retrieve")(_ctx(_FakeModel("PHAN TICH ok")))
    out = await role.run(WorkerInput(1, "rag_retrieve", "q", "trich"))
    assert out.output.startswith("PHAN TICH")


async def test_rag_retrieve_no_acl_no_info():
    ctx = RoleContext(mcp_client=_MockMCP(), user_id="u1", allowed_doc_ids=())
    out = await AGENT_REGISTRY.get("rag_retrieve")(ctx).run(WorkerInput(1, "rag_retrieve", "q"))
    assert out.status == "no_info"


async def test_hr_lookup_extracts_profile():
    out = await AGENT_REGISTRY.get("hr_lookup")(_ctx()).run(
        WorkerInput(2, "hr_lookup", {"intent": "leave_balance"}, "so phep"))
    assert out.status == "ok"
    assert "annual_remaining" in out.output


async def test_synthesize_no_model_falls_back_no_info():
    out = await AGENT_REGISTRY.get("synthesize_recommend")(_ctx()).run(
        WorkerInput(4, "synthesize_recommend", "q", "d", upstream={1: "x"}))
    assert out.status == "no_info"  # mini chết -> fallback an toàn, KHÔNG raise


async def test_role_never_raises_on_mcp_error():
    class _BadMCP:
        async def rag_search(self, *a, **k):
            raise RuntimeError("mcp down")

        async def call_tool(self, *a, **k):
            raise RuntimeError("mcp down")

    ctx = RoleContext(mcp_client=_BadMCP(), user_id="u1", allowed_doc_ids=("d1",))
    out = await AGENT_REGISTRY.get("rag_retrieve")(ctx).run(WorkerInput(1, "rag_retrieve", "q"))
    assert out.status == "error"  # trả error thay vì raise -> graph không vỡ
