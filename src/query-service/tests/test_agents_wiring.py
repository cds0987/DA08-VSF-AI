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
    """Bật AGENT_MODE=orchestrator_workers nhưng thiếu use_langgraph/base_url -> FAIL-CLOSED
    (raise rõ), KHÔNG âm thầm rơi về react (react không còn contract FE + bị CI chặn)."""
    monkeypatch.setenv("AGENT_MODE", "orchestrator_workers")
    from app.interfaces.api import dependencies as deps

    deps.get_settings.cache_clear()
    deps.get_orchestrator_planner.cache_clear()
    # conftest ép USE_LANGGRAPH=false -> thiếu điều kiện -> RAISE (không fallback)
    with pytest.raises(RuntimeError, match="orchestrator_workers"):
        deps._effective_agent_mode()
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


def _agent_mode_from_env_file(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("AGENT_MODE") and "=" in s and not s.startswith("#"):
            return s.split("=", 1)[1].strip().strip('"').strip("'").lower()
    return ""


def _agent_mode_from_compose(path):
    import re
    txt = path.read_text(encoding="utf-8")
    m = re.search(r"^\s*AGENT_MODE:\s*([^\s#]+)", txt, re.MULTILINE)
    return (m.group(1).strip().strip('"').strip("'").lower() if m else "")


def test_e2e_and_prod_agent_mode_consistent():
    """GATE quan trọng: AGENT_MODE trong docker-compose.e2e.yml PHẢI khớp deploy/env/
    query-service.env. -> e2e luôn test ĐÚNG path prod chạy. CI xanh = path đó đã validate
    end-to-end. Nếu lệch (vd prod bật orchestrator nhưng e2e vẫn react) -> CI đỏ -> chặn deploy
    untested path lên prod."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    env = root / "deploy" / "env" / "query-service.env"
    compose = root / "docker-compose.e2e.yml"
    if not (env.exists() and compose.exists()):
        pytest.skip("env/compose không có trong context build này")
    prod_mode = _agent_mode_from_env_file(env) or "react"
    e2e_mode = _agent_mode_from_compose(compose) or "react"
    assert prod_mode == e2e_mode, (
        f"AGENT_MODE LỆCH: prod={prod_mode!r} vs e2e={e2e_mode!r}. e2e PHẢI khớp prod để "
        "CI xanh thực sự chứng minh path prod chạy được."
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


class _FailModel:
    """Model giả MÔ PHỎNG timeout/lỗi: ainvoke luôn raise (không astream -> verify fallback acomplete)."""
    async def ainvoke(self, m):
        raise RuntimeError("LLM timeout (mô phỏng)")


@dataclass
class _User:
    id = "u1"; email = "u@x"; role = "employee"; account_type = "internal"; department = ""


async def test_verify_answer_llm_fail_khong_lo_raw_data():
    """REGRESSION (lỗi user gặp): khi LLM node verify_answer timeout/lỗi -> KHÔNG được word-chunk
    data_text thô ('[rag_retrieve...] {"results":[...]}') ra user. Phải thay bằng câu thân thiện."""
    from app.agents.manifest import load_manifest
    from app.agents.planners.orchestrator_workers import OrchestratorWorkersPlanner

    plan_json = (
        '{"route":"heavy","steps":['
        '{"id":1,"role":"rag_retrieve","input":"quy dinh","direction":"trich","depends_on":[]}]}'
    )

    def make_model(cap):
        if cap == "think":
            return _FakeModel(plan_json)   # planner OK -> có rag_retrieve -> data_text non-empty
        return _FailModel()                # answer/verify LLM LỖI -> verify_answer trả None

    uc = QueryOrchestrationUseCase(
        settings=Settings(rag_top_k=5, rag_score_threshold=0.45),
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

    events = [e async for e in uc._stream_inner("Toi con bao nhieu phep?", _User())]
    answer_text = "".join(str(e.get("token", "")) for e in events if e.get("token"))
    # TUYỆT ĐỐI không lộ format nội bộ ra user
    assert '"results"' not in answer_text, f"RÒ raw JSON ra user: {answer_text[:200]}"
    assert "[rag_retrieve" not in answer_text and "[hr_lookup" not in answer_text
    assert "12 ngay" not in answer_text  # parent_text thô (từ _Hit) không được word-chunk ra
    # vẫn phải có 1 done-event sạch (không treo)
    assert any(e.get("done") for e in events)


async def test_stream_safety_net_emits_done_when_stream_inner_raises():
    """LƯỚI AN TOÀN CUỐI: _stream_inner raise (DB/ACL/context fetch lỗi, hoặc bug bất kỳ TRƯỚC graph)
    -> stream() VẪN kết thúc bằng done-event hợp lệ + câu xin lỗi, KHÔNG để client đứt kết nối."""
    uc = QueryOrchestrationUseCase(
        settings=Settings(rag_top_k=5, rag_score_threshold=0.45),
        conversation_repo=_Repo(),
        document_access_repo=_AccessRepo(),
        semantic_cache=type("S", (), {"reset": lambda s: None})(),
        mcp_client=_MockMCP(),
        openai_client=object(),
        route_decision_provider=object(),
        guardrails=(_NoGuard(), _NoGuard()),
        agent_mode="orchestrator_workers",
        orchestrator_planner=None,
        make_model=None,
        agent_manifest=None,
    )

    async def _boom(*a, **k):
        raise RuntimeError("DB down (mô phỏng)")
        yield  # noqa — biến hàm thành async generator (raise ở __anext__ đầu)

    uc._stream_inner = _boom

    events = [e async for e in uc.stream("cau hoi", _User())]
    done = [e for e in events if e.get("done")]
    tokens = [e for e in events if e.get("token")]
    assert done, "stream() PHẢI emit done-event dù _stream_inner raise (else FE treo spinner)"
    # đủ field bắt buộc theo sse_contract.DONE_REQUIRED
    assert "session_id" in done[0] and "sources" in done[0]
    assert tokens and any("Helpdesk" in str(e.get("token", "")) for e in tokens), \
        "phải có câu xin lỗi thân thiện cho user"
