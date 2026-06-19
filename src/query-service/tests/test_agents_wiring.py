"""GATE wiring: orchestrator chỉ chạy khi BẬT tường minh; mặc định = path cũ (an toàn)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.application.use_cases.query.orchestration import QueryOrchestrationUseCase
from app.domain.outcome import Outcome
from app.infrastructure.config import Settings


# --- DEFAULT-OFF: dependency không bật orchestrator khi mode=react ---
def test_dependency_default_off_no_orchestrator(monkeypatch):
    monkeypatch.delenv("AGENT_MODE", raising=False)
    from app.interfaces.api import dependencies as deps

    deps.get_settings.cache_clear()
    deps.get_orchestrator_planner.cache_clear()
    assert deps._effective_agent_mode() == "react"
    assert deps.get_orchestrator_planner() is None


def test_dependency_orchestrator_needs_langgraph_and_router(monkeypatch):
    """Bật AGENT_MODE nhưng thiếu use_langgraph/base_url -> fail-safe về react."""
    monkeypatch.setenv("AGENT_MODE", "orchestrator_workers")
    from app.interfaces.api import dependencies as deps

    deps.get_settings.cache_clear()
    deps.get_orchestrator_planner.cache_clear()
    # conftest ép USE_LANGGRAPH=false -> thiếu điều kiện -> react
    assert deps._effective_agent_mode() == "react"
    deps.get_settings.cache_clear()
    deps.get_orchestrator_planner.cache_clear()


# --- ACTIVE: orchestrator path chạy end-to-end (planner/model giả) ---
@dataclass
class _Hit:
    document_name = "Quy dinh"; caption = "c"; parent_text = "12 ngay"
    heading_path = ("A",); score = 0.9; source_gcs_uri = "gs://x"
    document_id = "d1"; page_number = 1; chunk_id = "c1"


class _MockMCP:
    async def rag_search(self, query, document_ids, top_k):
        return [_Hit()]

    async def call_tool(self, name, args):
        return {"data": {"annual_remaining": 5}}


class _FakeModel:
    def __init__(self, t): self.t = t

    async def ainvoke(self, m):
        class R: pass
        r = R(); r.content = self.t; return r


class _Repo:
    async def get_context(self, *a, **k):
        class C: recent_messages = []
        return C()

    async def save_message(self, *a, **k):
        return "msg-1"

    async def add_message(self, *a, **k):
        return "msg-1"


class _AccessRepo:
    async def get_allowed_doc_ids(self, **k):
        return ["d1"]


class _NoGuard:
    async def scan(self, q):
        return (False, None)

    async def redact(self, a):
        return a


def test_committed_env_does_not_enable_orchestrator():
    """GATE prod: deploy/env/query-service.env KHÔNG được commit AGENT_MODE=orchestrator_workers.
    Bật chỉ qua override runtime trên canary -> tránh vỡ prod khi merge."""
    from pathlib import Path

    env = Path(__file__).resolve().parents[3] / "deploy" / "env" / "query-service.env"
    if not env.exists():
        pytest.skip("env file không có trong context build này")
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("AGENT_MODE"):
            val = line.split("=", 1)[1].strip().strip('"').strip("'").lower()
            assert val != "orchestrator_workers", (
                "deploy/env/query-service.env BẬT orchestrator_workers — phải để trống/react "
                "(default-off). Bật qua canary runtime, đừng commit."
            )


def test_orchestration_does_not_import_agents_at_module_load():
    """App boot KHÔNG được phụ thuộc agents module: import phải LAZY trong _stream_orchestrator.
    -> agents lỗi cú pháp/import vẫn không sập service (react path sống)."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app" / "application" / "use_cases" / "query" / "orchestration.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in tree.body:  # CHỈ xét top-level (module load)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            names = mod + " " + " ".join(n.name for n in getattr(node, "names", []))
            assert "app.agents" not in names, (
                f"orchestration.py import 'app.agents' ở top-level ({names}) -> agents lỗi sẽ "
                "sập app boot. Chuyển vào trong _stream_orchestrator (lazy)."
            )


async def test_orchestrator_path_runs_and_emits_sse():
    from app.agents.manifest import load_manifest
    from app.agents.planners.orchestrator_workers import OrchestratorWorkersPlanner

    plan_json = (
        '{"route":"heavy","steps":['
        '{"id":1,"role":"rag_retrieve","input":"quy dinh","direction":"trich","depends_on":[]},'
        '{"id":2,"role":"synthesize_recommend","input":"","direction":"tra loi","depends_on":[1]}]}'
    )

    def make_model(cap):
        if cap == "think":
            return _FakeModel(plan_json)
        return _FakeModel("Cau tra loi tong hop tu tai lieu.")

    settings = Settings(rag_top_k=5, rag_score_threshold=0.45)
    uc = QueryOrchestrationUseCase(
        settings=settings,
        conversation_repo=_Repo(),
        document_access_repo=_AccessRepo(),
        semantic_cache=type("S", (), {"reset": lambda s: None})(),
        mcp_client=_MockMCP(),
        openai_client=object(),
        route_decision_provider=object(),
        guardrails=(_NoGuard(), _NoGuard()),
        agent_mode="orchestrator_workers",
        orchestrator_planner=OrchestratorWorkersPlanner(),
        make_model=make_model,
        agent_manifest=load_manifest(),
    )

    @dataclass
    class _User:
        id = "u1"; email = "u@x"; role = "employee"; account_type = "internal"; department = ""

    events = [e async for e in uc._stream_inner("Toi con bao nhieu phep?", _User())]
    done = [e for e in events if e.get("done")]
    tokens = [e for e in events if e.get("token")]
    assert done and done[0]["agent_mode"] == "orchestrator_workers"
    assert done[0]["outcome"] == Outcome.SUCCESS.value
    assert len(done[0]["sources"]) == 1 and done[0]["sources"][0]["ref"] == 1
    assert tokens, "phải stream token câu trả lời"
