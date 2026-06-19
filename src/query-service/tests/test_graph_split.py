"""Phase 2 — tách answer node + per-node model wiring.

Kiểm offline (mock model, không mạng): answer_node quyết passthrough vs synthesize đúng,
và build_langgraph_agent chấp nhận cả models-dict lẫn 1 model dùng chung.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.application.langgraph_nodes import answer_node, _looks_like_action_json
from app.application.langgraph_state import AgentPhase
from app.application.langgraph_agent import build_langgraph_agent


class FakeModel:
    """Model giả: ghi lại messages nhận được, trả 1 AIMessage cố định."""

    def __init__(self, text: str = "Câu trả lời tổng hợp [1]."):
        self.text = text
        self.calls: list = []

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        return AIMessage(content=self.text)


def _state(**over):
    base = {
        "session_id": "s1",
        "iteration": 1,
        "phase": AgentPhase.THINKING,
        "messages": [],
        "tool_results": [],
        "sources": [],
        "shortcut_response": None,
        "shortcut_outcome": None,
    }
    base.update(over)
    return base


# --------------------------------------------------------------- action-json guard
def test_looks_like_action_json():
    assert _looks_like_action_json('{"action_type":"create_leave_request","items":[]}')
    assert _looks_like_action_json('  {"action_type":"review_leave_approvals"}  ')
    assert not _looks_like_action_json("Nhân viên được nghỉ 12 ngày [1].")
    assert not _looks_like_action_json("")


# ------------------------------------------------------------------- answer_node
async def test_answer_marker_when_split_off():
    fake = FakeModel()
    out = await answer_node(_state(messages=[AIMessage(content="x")]), model=fake, split=False)
    assert out["phase"] == AgentPhase.DONE
    assert "messages" not in out          # marker — không sinh mới
    assert fake.calls == []               # model KHÔNG được gọi


async def test_answer_passthrough_action_json():
    fake = FakeModel()
    msgs = [HumanMessage(content="cho tôi nghỉ mai"),
            AIMessage(content='{"action_type":"create_leave_request","items":[]}')]
    out = await answer_node(_state(messages=msgs, tool_results=[{"x": 1}]), model=fake, split=True)
    assert "messages" not in out          # giữ action JSON của think
    assert fake.calls == []


async def test_answer_passthrough_direct_answer_no_tools():
    fake = FakeModel()
    msgs = [HumanMessage(content="xin chào"), AIMessage(content="Chào bạn!")]
    out = await answer_node(_state(messages=msgs, tool_results=[]), model=fake, split=True)
    assert "messages" not in out          # trả lời trực tiếp, không cần synth
    assert fake.calls == []


async def test_answer_synthesizes_from_tool_results():
    fake = FakeModel(text="Tổng hợp từ tài liệu [1].")
    msgs = [
        HumanMessage(content="chính sách nghỉ phép?"),
        AIMessage(content="", tool_calls=[{"name": "rag_search", "args": {}, "id": "c1"}]),
        ToolMessage(content='{"results":[...]}', tool_call_id="c1", name="rag_search"),
        AIMessage(content="draft của think"),   # draft cuối -> phải bị bỏ trước khi synth
    ]
    out = await answer_node(_state(messages=msgs, tool_results=[{"ok": 1}]), model=fake, split=True)
    assert out["messages"][0].content == "Tổng hợp từ tài liệu [1]."
    sent = fake.calls[0]
    # Context SẠCH: system = synthesis prompt; KHÔNG còn ToolMessage / AIMessage-tool_calls;
    # kết quả tool gom vào 1 HumanMessage "[THÔNG TIN ĐÃ THU THẬP]".
    from langchain_core.messages import SystemMessage
    assert isinstance(sent[0], SystemMessage) and "KHÔNG gọi công cụ" in sent[0].content
    assert not any(isinstance(m, ToolMessage) for m in sent)
    assert not any(isinstance(m, AIMessage) and getattr(m, "tool_calls", None) for m in sent)
    assert any(isinstance(m, HumanMessage) and "THÔNG TIN ĐÃ THU THẬP" in m.content for m in sent)


async def test_answer_shortcut_is_marker_even_when_split():
    fake = FakeModel()
    out = await answer_node(
        _state(shortcut_response="canned", shortcut_outcome="OFF_TOPIC"),
        model=fake, split=True,
    )
    assert "messages" not in out
    assert fake.calls == []


# ----------------------------------------------------------------- build wiring
def test_build_agent_with_models_dict_split():
    agent = build_langgraph_agent(
        models={"triage": FakeModel(), "think": FakeModel(), "answer": FakeModel()},
        mcp_client=None,
        split_answer=True,
    )
    assert agent.name == "VinSmartFutureAgent"


def test_build_agent_back_compat_single_model():
    agent = build_langgraph_agent(model=FakeModel(), mcp_client=None)
    assert agent.name == "VinSmartFutureAgent"
