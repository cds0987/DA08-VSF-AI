"""GATE: hợp đồng SSE (sse_contract.py) là 1 NGUỒN SỰ THẬT — chặn dev thêm node/phase mà
quên khai cách hiển thị (-> event câm trên UI) hoặc đổi shape done-event (-> FE treo).

Các gate này kiểm CONTRACT, KHÔNG kiểm từng node -> thêm node KHÔNG cần thêm test: chỉ cần
khai NodeDescriptor trong NODES, các gate dưới tự ép. Đây là "test chặt nhưng linh hoạt theo
độ mở rộng của agents".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.agents import planners, roles  # noqa: F401 — register
from app.agents.base import RoleContext
from app.agents.graph_builder import build_orchestrator_graph
from app.agents.manifest import load_manifest
from app.agents.registry import PLANNER_REGISTRY
from app.agents.sse_contract import (
    CONTRACT_VERSION,
    DONE_REQUIRED,
    GROUPS,
    NODES,
    PHASES,
    contract_manifest,
    validate_event,
)

_APP = Path(__file__).resolve().parent.parent / "app"

# File PHÁT event SSE (emit producers) — scan các file này tìm literal phase/node.
_EMIT_SOURCES = [
    _APP / "agents" / "graph_builder.py",
    _APP / "agents" / "roles" / "_llm.py",
    _APP / "agents" / "roles" / "rag_retrieve.py",
    _APP / "agents" / "roles" / "hr_lookup.py",
    _APP / "agents" / "roles" / "leave_action.py",
    _APP / "agents" / "planners" / "orchestrator_workers.py",
    _APP / "application" / "use_cases" / "query" / "orchestration.py",
]

# Drift gate: đổi tập này = THAY ĐỔI CÓ Ý THỨC (phải sửa cả FE codegen). Vô tình thêm = đỏ.
_EXPECTED_PHASES = {
    "thinking", "acting", "observing", "generating",
    "plan", "step", "thought", "model_used",
}
_EXPECTED_NODES = {"orchestrate", "plan", "think", "act", "verify", "answer"}


def _scan(pattern: str) -> set[str]:
    """Gom mọi capture-group khớp `pattern` qua các file emit source."""
    rx = re.compile(pattern)
    found: set[str] = set()
    for f in _EMIT_SOURCES:
        if not f.exists():
            continue
        for m in rx.finditer(f.read_text(encoding="utf-8")):
            found.add(m.group(1))
    return found


# ───────────────────────────── GATE 1: no undeclared phase ─────────────────────────────
def test_gate_every_emitted_phase_is_declared():
    """Mọi literal `"phase": "X"` và `current_phase = "X"` trong code emit PHẢI ∈ PHASES.
    Thêm phase mới mà quên khai -> đỏ (FE sẽ không biết xử lý phase đó)."""
    used = _scan(r'"phase":\s*"([a-z_]+)"') | _scan(r'current_phase\s*=\s*"([a-z_]+)"')
    undeclared = used - set(PHASES)
    assert not undeclared, (
        f"Phase emit nhưng CHƯA khai trong sse_contract.PHASES: {sorted(undeclared)} "
        "-> thêm vào PHASES (+ _EXPECTED_PHASES) để FE biết xử lý."
    )


# ───────────────────────────── GATE 2: no silent node ─────────────────────────────
def test_gate_every_emitted_node_is_declared():
    """Mọi literal `"node": "X"` và `node="X"` (default + call-site) PHẢI ∈ NODES.
    Đây là chốt chặn 'thêm node vào graph -> phải có cách hiển thị, KHÔNG câm trên UI'."""
    used = _scan(r'"node":\s*"([a-z_]+)"') | _scan(r'\bnode\s*=\s*"([a-z_]+)"')
    undeclared = used - set(NODES)
    assert not undeclared, (
        f"Node emit nhưng CHƯA khai NodeDescriptor: {sorted(undeclared)} "
        "-> thêm vào sse_contract.NODES (label+group+icon) để FE render được, else CÂM."
    )


# ───────────────────────────── GATE 3 & 4: drift + descriptor đầy đủ ─────────────────────────────
def test_gate_phases_match_expected_snapshot():
    assert set(PHASES) == _EXPECTED_PHASES, (
        "PHASES đổi so với snapshot — nếu CỐ Ý, cập nhật _EXPECTED_PHASES + chạy lại "
        "codegen FE (scripts/gen_sse_contract.py)."
    )


def test_gate_nodes_match_expected_snapshot():
    assert set(NODES) == _EXPECTED_NODES, (
        "NODES đổi so với snapshot — nếu CỐ Ý (thêm node), cập nhật _EXPECTED_NODES + "
        "chạy lại codegen FE."
    )


def test_gate_every_node_has_complete_descriptor():
    """Mỗi node PHẢI có label + group ∈ GROUPS + icon (để FE render generic)."""
    for name, d in NODES.items():
        assert d.name == name, f"NODES key {name!r} != descriptor.name {d.name!r}"
        assert d.label, f"node {name!r} thiếu label"
        assert d.group in GROUPS, f"node {name!r}: group {d.group!r} không ∈ GROUPS {GROUPS}"
        assert d.icon, f"node {name!r} thiếu icon"


# ───────────────────────────── GATE 5: done-event required ─────────────────────────────
def test_gate_validate_catches_done_missing_required():
    full = {"done": True, "session_id": "s", "sources": []}
    assert validate_event(full) == []
    bad = {"done": True, "sources": []}  # thiếu session_id
    problems = validate_event(bad)
    assert problems and "session_id" in problems[0]
    with pytest.raises(ValueError):
        validate_event(bad, strict=True)


def test_gate_validate_catches_unknown_phase_and_node():
    assert validate_event({"phase": "thinking", "node": "verify"}) == []
    assert validate_event({"token": "hi"}) == []  # token delta thuần -> hợp lệ
    assert validate_event({"phase": "nope"})       # unknown phase -> có vấn đề
    assert validate_event({"phase": "thought", "node": "ghost"})  # unknown node -> có vấn đề


def test_gate_done_required_matches_fe_isDoneEvent():
    """done_required PHẢI khớp FE.isDoneEvent (done+session_id+sources). Đổi 1 đầu mà quên đầu
    kia -> tin nhắn treo. Đọc FE chat.ts để so."""
    fe = (Path(__file__).resolve().parents[2] / "frontend" / "chat" / "app" / "stores" / "chat.ts")
    if not fe.exists():
        pytest.skip("FE không có trong checkout này")
    src = fe.read_text(encoding="utf-8")
    body = src[src.find("function isDoneEvent"): src.find("function isDoneEvent") + 600]
    for field in DONE_REQUIRED:
        assert field in body, (
            f"FE.isDoneEvent KHÔNG kiểm {field!r} nhưng contract.DONE_REQUIRED có -> lệch hợp đồng."
        )


# ───────────────────────────── GATE 6: runtime — mọi event graph phát ra HỢP LỆ ─────────────────
class _Hit:
    document_name = "Quy dinh"; caption = "c"; parent_text = "12 ngay"
    heading_path = ("A",); score = 0.8; source_gcs_uri = "gs://x"
    document_id = "d1"; page_number = 1; chunk_id = "c1"


class _MCP:
    async def rag_search(self, *a, **k):
        return [_Hit()]

    async def call_tool(self, *a, **k):
        return {"data": {"annual_remaining": 5}}


class _FakeModel:
    def __init__(self, t): self.t = t

    async def ainvoke(self, m):
        class R: pass
        r = R(); r.content = self.t; return r


_PLAN_JSON = (
    '{"route":"heavy","steps":['
    '{"id":1,"role":"rag_retrieve","input":"quy dinh","direction":"trich","depends_on":[]}]}'
)


def _mk(plan_json):
    def f(cap):
        if cap in ("plan", "think"):
            return _FakeModel(plan_json)
        if cap in ("answer", "synth"):
            return _FakeModel('{"sufficient": true} TRA LOI [1]')
        return _FakeModel("worker output")
    return f


async def test_gate_runtime_all_graph_events_valid():
    """Chạy THẬT orchestrator graph, BẮT mọi event emit -> mỗi event PHẢI hợp lệ theo contract.
    Đây là gate 'không phát event lạ' chạy động (bổ sung scan tĩnh)."""
    events: list[dict] = []

    async def emit(ev):
        events.append(ev)

    ctx = RoleContext(mcp_client=_MCP(), user_id="u1", allowed_doc_ids=("d1",),
                      rag_top_k=5, rag_score_threshold=0.45, make_model=_mk(_PLAN_JSON), emit=emit)
    g = build_orchestrator_graph(ctx=ctx, manifest=load_manifest(),
                                 planner=PLANNER_REGISTRY.get("orchestrator_workers")(),
                                 make_model=_mk(_PLAN_JSON))
    await g.ainvoke({"question": "Toi con bao nhieu phep va quy dinh?"})
    assert events, "graph không phát event nào?"
    for ev in events:
        problems = validate_event(ev)
        assert not problems, f"event KHÔNG hợp lệ theo contract: {ev} -> {problems}"


# ───────────────────────────── GATE 7: manifest = nguồn cho FE codegen ─────────────────
def test_gate_manifest_json_serializable_and_shaped():
    m = contract_manifest()
    s = json.dumps(m, ensure_ascii=False)   # phải serialize được (FE đọc JSON)
    assert json.loads(s)["version"] == CONTRACT_VERSION
    assert set(m["nodes"]) == set(NODES)
    for nd in m["nodes"].values():
        assert nd["group"] in m["groups"]
        assert nd["label"] and nd["icon"]
    assert set(m["phases"]) == set(PHASES)
    assert set(m["done_required"]) == set(DONE_REQUIRED)
