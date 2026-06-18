"""
Triage routing tests (T2).

triage_node dùng LLM để phân loại nên CHẤT LƯỢNG prompt (câu policy rõ → ALLOW,
không CLARIFY) phải verify bằng LLM thật trên VM + Langfuse. Ở đây ta khóa HỢP ĐỒNG
routing của node: với mỗi route LLM trả về, node phải map sang shortcut_outcome đúng.
Fake model trả JSON cố định (không gọi OpenAI thật).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.application.langgraph_nodes import triage_node


class _FakeChatModel:
    """Chat model giả: ainvoke() trả AIMessage-like với content cố định."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[list] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self._content, tool_calls=[])


def _state(question: str) -> dict:
    return {
        "question": question,
        "session_id": "sess-test",
        "messages": [],
    }


async def test_clear_policy_question_routes_allow():
    # Câu policy đã rõ ("chính sách nghỉ phép hàng năm") → ALLOW: node trả {} để
    # rơi xuống think_node, KHÔNG đặt shortcut_outcome=CLARIFY.
    model = _FakeChatModel('{"route":"ALLOW","reason":"internal policy question"}')
    result = await triage_node(_state("Chính sách nghỉ phép hàng năm là gì?"), model)
    assert result == {}


async def test_vague_question_routes_clarify():
    model = _FakeChatModel(
        '{"route":"CLARIFY","clarify_question":"Bạn muốn hỏi về thiết bị nào?","reason":"too vague"}'
    )
    result = await triage_node(_state("Nó bị hỏng rồi"), model)
    assert result["shortcut_outcome"] == "CLARIFY"
    assert "thiết bị" in result["shortcut_response"]


async def test_offtopic_routes_refuse():
    model = _FakeChatModel('{"route":"REFUSE","reason":"out of scope"}')
    result = await triage_node(_state("Thời tiết hôm nay thế nào?"), model)
    assert result["shortcut_outcome"] == "OFF_TOPIC"


async def test_safety_emergency_routes_success():
    model = _FakeChatModel('{"route":"SAFETY","safety_type":"emergency","reason":"fire"}')
    result = await triage_node(_state("Cháy rồi"), model)
    assert result["shortcut_outcome"] == "SUCCESS"


async def test_clarify_without_question_uses_fallback():
    model = _FakeChatModel('{"route":"CLARIFY","reason":"vague"}')
    result = await triage_node(_state("Cho hỏi chút"), model)
    assert result["shortcut_outcome"] == "CLARIFY"
    assert result["shortcut_response"]  # fallback message, không rỗng


async def test_malformed_json_defaults_to_allow():
    # Parse lỗi → ALLOW (không bao giờ từ chối nhầm câu hợp lệ).
    model = _FakeChatModel("not-a-json")
    result = await triage_node(_state("Chính sách công tác phí?"), model)
    assert result == {}


async def test_legacy_label_off_topic_aliases_to_refuse():
    # Backward-compat: nhãn cũ off_topic → REFUSE.
    model = _FakeChatModel('{"route":"off_topic","reason":"legacy label"}')
    result = await triage_node(_state("Giá vàng hôm nay?"), model)
    assert result["shortcut_outcome"] == "OFF_TOPIC"


async def test_meta_sources_with_cited_names_includes_followup():
    # META/sources khi lịch sử có [Nguồn tham khảo:...] → liệt kê tên + mời hỏi tiếp.
    from types import SimpleNamespace as SN
    from langchain_core.messages import AIMessage

    ai_msg = AIMessage(
        content="Đây là thông tin HR.\n[Nguồn tham khảo: HR_Policy.pdf, CNHC_Handbook.pdf]"
    )
    state = {
        "question": "10 file trên là file gì vậy",
        "session_id": "sess-test",
        "messages": [ai_msg],
    }
    model = _FakeChatModel('{"route":"META","meta_type":"sources","reason":"numeric file reference"}')
    result = await triage_node(state, model)
    assert result["shortcut_outcome"] == "SUCCESS"
    assert "HR_Policy.pdf" in result["shortcut_response"]
    assert "CNHC_Handbook.pdf" in result["shortcut_response"]
    # Phải có lời mời hỏi tiếp
    assert "tra cứu" in result["shortcut_response"]


async def test_meta_sources_without_cited_names_asks_for_clarification():
    # META/sources khi không tìm thấy [Nguồn tham khảo:] → mời user chỉ rõ file.
    state = {
        "question": "10 file trên là file gì vậy",
        "session_id": "sess-test",
        "messages": [],
    }
    model = _FakeChatModel('{"route":"META","meta_type":"sources","reason":"numeric file reference"}')
    result = await triage_node(state, model)
    assert result["shortcut_outcome"] == "SUCCESS"
    assert "không tìm thấy" in result["shortcut_response"]
    # Phải mời user làm rõ
    assert "file" in result["shortcut_response"].lower() or "tài liệu" in result["shortcut_response"].lower()
