"""Phase 3 — log/trace per-node mang đủ field để dò bug (adapter/model/effort)."""
from __future__ import annotations

import logging

from app.application.langgraph_nodes import _model_trace_fields, answer_node
from app.application.langgraph_state import AgentPhase


class _ModelLike:
    adapter_name = "reasoning_oai"
    model = "think"
    reasoning_effort = "medium"


def test_model_trace_fields_from_mosa():
    f = _model_trace_fields(_ModelLike())
    assert f == {"adapter": "reasoning_oai", "model_id": "think", "reasoning_effort": "medium"}


def test_model_trace_fields_safe_on_plain_object():
    assert _model_trace_fields(object()) == {"adapter": None, "model_id": None, "reasoning_effort": None}
    assert _model_trace_fields(None) == {"adapter": None, "model_id": None, "reasoning_effort": None}


async def test_answer_node_log_carries_trace_fields(caplog):
    state = {
        "session_id": "s1", "iteration": 1, "phase": AgentPhase.THINKING,
        "messages": [], "tool_results": [], "sources": [],
        "shortcut_response": None, "shortcut_outcome": None,
    }
    with caplog.at_level(logging.INFO, logger="app.application.langgraph_nodes"):
        await answer_node(state, model=_ModelLike(), split=False)
    rec = next(r for r in caplog.records if r.message == "langgraph_answer")
    assert getattr(rec, "adapter") == "reasoning_oai"
    assert getattr(rec, "model_id") == "think"
    assert getattr(rec, "reasoning_effort") == "medium"
    assert getattr(rec, "session_id") == "s1"
