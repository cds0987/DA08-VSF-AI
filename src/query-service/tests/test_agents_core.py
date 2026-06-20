"""Unit: registry + plan_schema + bus + manifest (MOSA multi-agent core)."""
from __future__ import annotations

import pytest

from app.agents import roles  # noqa: F401 — side-effect register
from app.agents.base import WorkerOutput
from app.agents.bus import aggregate_sources, merge_step_results, upstream_outputs
from app.agents.manifest import load_manifest
from app.agents.plan_schema import Plan
from app.agents.registry import AGENT_REGISTRY


# --- registry -----------------------------------------------------------------
def test_registry_roles_registered():
    for name in ("rag_retrieve", "hr_lookup", "analyze", "synthesize_recommend", "critic"):
        assert AGENT_REGISTRY.has(name), f"role '{name}' chưa đăng ký"


def test_registry_duplicate_raises():
    from app.agents.registry import Registry

    r = Registry("x")
    r.register("a", object())
    with pytest.raises(ValueError):
        r.register("a", object())
    r.register("a", object(), override=True)  # override OK


# --- plan_schema --------------------------------------------------------------
def test_plan_dag_ready_steps():
    p = Plan.model_validate({"route": "heavy", "steps": [
        {"id": 1, "role": "rag_retrieve", "input": "q", "depends_on": []},
        {"id": 2, "role": "hr_lookup", "input": {}, "depends_on": []},
        {"id": 3, "role": "synthesize_recommend", "depends_on": [1, 2]},
    ]})
    assert {s.id for s in p.ready_steps(set())} == {1, 2}
    assert [s.id for s in p.ready_steps({1, 2})] == [3]


def test_plan_accepts_null_answer_hint_and_reasoning():
    """Planner LLM hay xuất answer_hint/reasoning = null ở route=heavy -> PHẢI parse OK
    (coerce -> ""), KHÔNG fail gây retry gọi lại planner chậm (điểm nghẽn latency)."""
    p = Plan.model_validate({
        "route": "heavy", "reasoning": None, "answer_hint": None,
        "steps": [{"id": 1, "role": "rag_retrieve", "input": "q", "direction": None, "depends_on": []}],
    })
    assert p.answer_hint == "" and p.reasoning == ""
    assert p.steps[0].direction == ""


def test_plan_rejects_cycle():
    with pytest.raises(Exception):
        Plan.model_validate({"route": "heavy", "steps": [
            {"id": 1, "role": "a", "depends_on": [2]},
            {"id": 2, "role": "b", "depends_on": [1]},
        ]})


def test_plan_rejects_unknown_dep_and_empty_heavy():
    with pytest.raises(Exception):
        Plan.model_validate({"route": "heavy", "steps": [
            {"id": 1, "role": "a", "depends_on": [99]}]})
    with pytest.raises(Exception):
        Plan.model_validate({"route": "heavy", "steps": []})


# --- bus reducer --------------------------------------------------------------
def test_merge_step_results_no_clobber():
    a = {1: WorkerOutput(1, "r", "A", sources=[{"s": 1}])}
    b = {2: WorkerOutput(2, "r", "B", sources=[{"s": 2}])}
    m = merge_step_results(a, b)
    assert set(m) == {1, 2}
    assert merge_step_results(None, a) == a
    assert aggregate_sources(m) == [{"s": 1}, {"s": 2}]


def test_upstream_outputs():
    res = {1: WorkerOutput(1, "r", "out1"), 2: WorkerOutput(2, "r", "out2")}
    assert upstream_outputs(res, [1]) == {1: "out1"}
    assert upstream_outputs(res, [9]) == {}  # dep chưa có -> bỏ qua


# --- manifest -----------------------------------------------------------------
def test_manifest_loads_and_fallback_safe():
    m = load_manifest()
    assert m.mode in ("react", "orchestrator_workers")
    # critic enabled:false -> không nằm trong enabled_roles
    assert "critic" not in {r.name for r in m.enabled_roles()}


def test_manifest_bad_path_fallback_react():
    m = load_manifest.__wrapped__("/khong/ton/tai/agents.yaml")  # bypass lru_cache
    assert m.mode == "react"
