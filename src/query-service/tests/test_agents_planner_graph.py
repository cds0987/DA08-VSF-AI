"""Integration: orchestrator planner + graph_builder (fan-out song song theo DAG)."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.agents import planners, roles  # noqa: F401 — register
from app.agents.base import RoleContext
from app.agents.graph_builder import build_orchestrator_graph
from app.agents.manifest import load_manifest
from app.agents.planners.base import PlanContext
from app.agents.registry import PLANNER_REGISTRY

_PLAN_JSON = (
    '{"route":"heavy","steps":['
    '{"id":1,"role":"hr_lookup","input":{"intent":"leave_balance"},"direction":"so phep","depends_on":[]},'
    '{"id":2,"role":"rag_retrieve","input":"quy dinh","direction":"trich","depends_on":[]},'
    '{"id":3,"role":"synthesize_recommend","input":"","direction":"khuyen nghi","depends_on":[1,2]}]}'
)


@dataclass
class _Hit:
    document_name = "Quy dinh"; caption = "c"; parent_text = "12 ngay"
    heading_path = ("A",); score = 0.8; source_gcs_uri = "gs://x"
    document_id = "d1"; page_number = 1; chunk_id = "c1"


class _SlowMCP:
    async def rag_search(self, *a, **k):
        await asyncio.sleep(0.2); return [_Hit()]

    async def call_tool(self, *a, **k):
        await asyncio.sleep(0.2); return {"data": {"annual_remaining": 5}}


class _FakeModel:
    def __init__(self, t): self.t = t

    async def ainvoke(self, m):
        class R: pass
        r = R(); r.content = self.t; return r


def _make_model(plan_json):
    def mk(cap):
        if cap == "think":
            return _FakeModel(plan_json)
        if cap == "answer":
            return _FakeModel("TRA LOI tong hop")
        return _FakeModel("worker output")
    return mk


async def test_planner_heavy_and_fallback():
    planner = PLANNER_REGISTRY.get("orchestrator_workers")()
    catalog = load_manifest().enabled_roles()
    # heavy hợp lệ
    p = await planner.plan(PlanContext("q", catalog, _make_model(_PLAN_JSON)))
    assert p.route == "heavy" and len(p.steps) == 3
    # role sai -> retry -> fallback (vẫn có synthesize)
    bad = '{"route":"heavy","steps":[{"id":1,"role":"hacker","input":"x","depends_on":[]}]}'
    p = await planner.plan(PlanContext("q", catalog, _make_model(bad)))
    assert "synthesize_recommend" in {s.role for s in p.steps}
    # no model -> fallback
    p = await planner.plan(PlanContext("q", catalog, None))
    assert p.route == "heavy"


async def test_graph_heavy_runs_workers_in_parallel():
    ctx = RoleContext(mcp_client=_SlowMCP(), user_id="u1", allowed_doc_ids=("d1",),
                      rag_top_k=5, rag_score_threshold=0.45, make_model=_make_model(_PLAN_JSON))
    g = build_orchestrator_graph(ctx=ctx, manifest=load_manifest(),
                                 planner=PLANNER_REGISTRY.get("orchestrator_workers")(),
                                 make_model=_make_model(_PLAN_JSON))
    t = time.time()
    res = await g.ainvoke({"question": "Toi con bao nhieu phep va quy dinh?"})
    dt = time.time() - t
    assert res["answer"]
    assert len(res["results"]) == 3
    # 2 worker 0.2s SONG SONG -> tổng < 0.6s (nếu tuần tự sẽ ~0.4s+ chỉ riêng 2 worker)
    assert dt < 0.6, f"nghi tuan tu: {dt:.2f}s"


async def test_graph_light_skips_workers():
    light = '{"route":"light","answer_hint":"Xin chao!","steps":[]}'
    ctx = RoleContext(mcp_client=_SlowMCP(), user_id="u1", allowed_doc_ids=("d1",),
                      make_model=_make_model(light))
    g = build_orchestrator_graph(ctx=ctx, manifest=load_manifest(),
                                 planner=PLANNER_REGISTRY.get("orchestrator_workers")(),
                                 make_model=_make_model(light))
    res = await g.ainvoke({"question": "hello"})
    assert res["answer"] == "Xin chao!"
    assert not res.get("results")  # không gọi worker nào
