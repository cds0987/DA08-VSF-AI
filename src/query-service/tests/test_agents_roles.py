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


class _StreamModel:
    """Model giả có astream: phát reasoning_content (model 'nghĩ') rồi content (câu trả lời)."""
    def __init__(self, reasoning_parts, content_parts):
        self._r = reasoning_parts
        self._c = content_parts

    async def astream(self, msgs):
        from langchain_core.messages import AIMessageChunk
        for r in self._r:
            yield AIMessageChunk(content="", additional_kwargs={"reasoning_content": r})
        for c in self._c:
            yield AIMessageChunk(content=c)


async def test_astream_complete_surfaces_reasoning_and_streams_content():
    """FIX hiệu ứng: reasoning_content -> SSE thought (user THẤY model nghĩ live); content ->
    token generating (câu trả lời chạy dần). Trước đây reasoning bị BỎ -> UI im lặng/trả 1 cục."""
    from app.agents.roles._llm import astream_complete

    events: list[dict] = []

    async def emit(ev):
        events.append(ev)

    model = _StreamModel(["Đang cân nhắc ", "dữ liệu…"], ["Xin ", "chào ", "bạn!"])
    text = await astream_complete(model, "sys", "user", emit, node="answer")

    assert text == "Xin chào bạn!"
    thoughts = [e for e in events if e.get("phase") == "thought" and e.get("node") == "answer"]
    tokens = [e for e in events if e.get("token")]
    assert thoughts, "reasoning_content KHÔNG được surface ra SSE -> UI im lặng khi model nghĩ"
    assert len(tokens) == 3 and "".join(t["token"] for t in tokens) == "Xin chào bạn!"


async def test_astream_reasoning_emits_thought_but_not_content_tokens():
    """planner/verify: reasoning -> thought live; content (JSON) chỉ gom, KHÔNG emit token JSON."""
    from app.agents.roles._llm import astream_reasoning

    events: list[dict] = []

    async def emit(ev):
        events.append(ev)

    model = _StreamModel(["Phân tích ", "câu hỏi…"], ['{"sufficient":', ' true}'])
    text = await astream_reasoning(model, "sys", "user", emit, node="verify")

    assert text == '{"sufficient": true}'
    assert [e for e in events if e.get("phase") == "thought" and e.get("node") == "verify"]
    assert not [e for e in events if e.get("token")], "KHÔNG được leak JSON content ra token SSE"


class _DateMCP:
    """resolve_date giả: span_days>1 -> start/end; 1 ngày -> date. today cố định để test past-check."""
    async def call_tool(self, name, args):
        assert name == "resolve_date"
        if int(args.get("span_days") or 1) > 1:
            return {"start_date": "2026-06-22", "end_date": "2026-06-24", "today": "2026-06-20"}
        return {"date": "2026-06-22", "today": "2026-06-20"}


def _ctx_date(model=None):
    return RoleContext(
        mcp_client=_DateMCP(), user_id="u1", allowed_doc_ids=(),
        make_model=(lambda cap: model) if model else None,
    )


async def test_leave_action_creates_draft_json():
    """create-leave -> PURE JSON action create_leave_request (FE render form). Ngày qua resolve_date."""
    import json
    model = _FakeModel(
        '{"intent":"create","leave_type":"sick","items":[{"date_spec":'
        '{"kind":"weekday","weekday":"thu_2","week_offset":1,"span_days":3},"reason":"ốm"}]}'
    )
    out = await AGENT_REGISTRY.get("leave_action")(_ctx_date(model)).run(
        WorkerInput(1, "leave_action", "nghỉ ốm 3 ngày thứ 2 tuần sau"))
    assert out.status == "ok"
    data = json.loads(out.output)
    assert data["action_type"] == "create_leave_request"
    item = data["items"][0]
    assert item["leave_type"] == "sick"
    assert item["start_date"] == "2026-06-22" and item["end_date"] == "2026-06-24"


async def test_leave_action_clarifies_when_type_missing():
    """Không có loại nghỉ + lý do -> hỏi làm rõ (văn xuôi), KHÔNG bịa đơn annual."""
    model = _FakeModel('{"intent":"clarify","clarify":"Bạn muốn nghỉ loại nào — phép năm hay nghỉ ốm?"}')
    out = await AGENT_REGISTRY.get("leave_action")(_ctx_date(model)).run(
        WorkerInput(1, "leave_action", "cho tôi nghỉ thứ 2 tuần sau"))
    assert out.status == "ok"
    assert "action_type" not in out.output and "loại nào" in out.output


async def test_leave_action_approve_emits_review_card():
    model = _FakeModel('{"intent":"approve"}')
    out = await AGENT_REGISTRY.get("leave_action")(_ctx_date(model)).run(
        WorkerInput(1, "leave_action", "duyệt giúp tôi các đơn chờ"))
    assert '"action_type": "review_leave_approvals"' in out.output


async def test_leave_action_no_model_clarifies():
    ctx = RoleContext(mcp_client=_DateMCP(), user_id="u1")
    out = await AGENT_REGISTRY.get("leave_action")(ctx).run(WorkerInput(1, "leave_action", "nghỉ phép"))
    assert out.status == "ok" and "action_type" not in out.output


async def test_role_never_raises_on_mcp_error():
    class _BadMCP:
        async def rag_search(self, *a, **k):
            raise RuntimeError("mcp down")

        async def call_tool(self, *a, **k):
            raise RuntimeError("mcp down")

    ctx = RoleContext(mcp_client=_BadMCP(), user_id="u1", allowed_doc_ids=("d1",))
    out = await AGENT_REGISTRY.get("rag_retrieve")(ctx).run(WorkerInput(1, "rag_retrieve", "q"))
    assert out.status == "error"  # trả error thay vì raise -> graph không vỡ
