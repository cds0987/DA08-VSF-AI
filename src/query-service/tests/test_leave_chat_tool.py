"""Khóa hành vi: tool WRITE (vd create_leave_request) được dùng QUA LUỒNG ĐỘNG —
discover từ MCP, act_node thực thi generic, user_id tiêm server-side, KHÔNG hardcode.

Khác test_tool_discovery (tool trả 'summary'): tool write trả dict đơn (id/status/...)
KHÔNG có key summary -> act_node phải fallback json.dumps -> LLM vẫn nhận được data.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from app.application.langgraph_nodes import act_node, build_langgraph_tools
from app.application.langgraph_state import create_initial_state
from app.application.ports import ToolSpec

_CREATE_SPEC = {
    "name": "create_leave_request",
    "description": "Tạo đơn xin nghỉ phép cho user hiện tại.",
    "input_schema": {
        "type": "object",
        "properties": {
            "leave_type": {"type": "string"},
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["leave_type", "start_date", "end_date"],
    },
}
_CREATE_RESPONSE = {"id": "req-77", "status": "pending", "approver_user_id": "mgr-1", "days_count": 2}


def _mcp():
    from app.interfaces.api.dependencies import get_mcp_client
    return get_mcp_client()


def _register():
    _mcp().register_tool(spec=ToolSpec(**_CREATE_SPEC), response=_CREATE_RESPONSE)


@pytest.mark.asyncio
async def test_write_tool_discovered_dynamically():
    _register()
    tools = await build_langgraph_tools(
        mcp_client=_mcp(), allowed_doc_ids=frozenset(["doc-1"]), user_id="u-test"
    )
    names = [(t["name"] if isinstance(t, dict) else t.name) for t in tools]
    assert "create_leave_request" in names  # tự xuất hiện, KHÔNG hardcode


@pytest.mark.asyncio
async def test_acl_loader_exposes_typed_params_for_create():
    """get_acl_tools (đường prod) build create_leave_request thành StructuredTool KIỂU
    -> model THẤY args (leave_type/start_date/end_date), KHÔNG còn gọi rỗng {}."""
    from langchain_core.utils.function_calling import convert_to_openai_function
    from app.infrastructure.config import get_settings
    from app.infrastructure.external.langchain_mcp_client import LangChainMCPToolsLoader

    _register()
    loader = LangChainMCPToolsLoader(settings=get_settings(), mcp_client=_mcp())
    tools = await loader.get_acl_tools(user_id="u1", allowed_doc_ids=frozenset())
    create = next(t for t in tools if getattr(t, "name", None) == "create_leave_request")
    fn = convert_to_openai_function(create)
    props = fn["parameters"].get("properties", {})
    assert {"leave_type", "start_date", "end_date"} <= set(props)
    assert set(fn["parameters"].get("required", [])) >= {"leave_type", "start_date", "end_date"}


@pytest.mark.asyncio
async def test_act_node_executes_write_tool_and_injects_user_id():
    _register()
    mcp = _mcp()
    initial = create_initial_state(
        question="Tôi muốn xin nghỉ phép năm 1-2/9",
        user_id="u-test", user_role="employee", user_department="IT",
        allowed_doc_ids=["doc-1"], session_id="s1", max_iterations=3, recent_messages=[],
    )
    ai = AIMessage(content="", tool_calls=[{
        "name": "create_leave_request",
        "args": {"leave_type": "annual", "start_date": "2026-09-01", "end_date": "2026-09-02"},
        "id": "call_1", "type": "tool_call",
    }])
    result = await act_node({**initial, "messages": [ai]}, mcp_client=mcp)

    # Data của đơn tới được LLM (fallback json vì không có 'summary')
    msgs = [m for m in result.get("messages", []) if hasattr(m, "content")]
    assert msgs and "req-77" in msgs[0].content and "pending" in msgs[0].content
    # user_id tiêm server-side (không từ LLM args)
    last = mcp.last_tool_calls[-1]
    assert last.tool_name == "create_leave_request"
    assert last.arguments.get("user_id") == "u-test"
