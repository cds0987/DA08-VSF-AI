"""Regression: _astream phải gom function-call arguments theo `item_id` (event
response.function_call_arguments.delta dùng item_id, KHÔNG phải call_id).

Bug cũ: key fn_calls theo call_id -> delta (item_id) rớt -> tool_call.args = {} ->
tool cần args (create_leave_request) bị gọi rỗng -> hr 422. Test này khóa lại.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.infrastructure.external.langchain_responses_adapter import OpenAIResponsesChatModel


class _Input(BaseModel):
    leave_type: str = Field(description="loại")
    start_date: str = Field(description="bắt đầu")
    end_date: str = Field(description="kết thúc")


def _tool():
    async def _run(**kw):
        return "{}"
    return StructuredTool.from_function(
        coroutine=_run, name="create_leave_request", description="tạo đơn", args_schema=_Input
    )


class _FakeResponses:
    def __init__(self, events):
        self._events = events

    async def create(self, **kwargs):
        events = self._events

        async def _gen():
            for e in events:
                yield e

        return _gen()


class _FakeClient:
    def __init__(self, events):
        self.responses = _FakeResponses(events)


@pytest.mark.asyncio
async def test_astream_accumulates_args_by_item_id():
    events = [
        SimpleNamespace(
            type="response.output_item.added",
            item=SimpleNamespace(type="function_call", id="fc_1", call_id="call_1",
                                 name="create_leave_request"),
        ),
        # delta định danh theo item_id (= "fc_1"), KHÔNG có call_id
        SimpleNamespace(type="response.function_call_arguments.delta", item_id="fc_1",
                        delta='{"leave_type":"annual",'),
        SimpleNamespace(type="response.function_call_arguments.delta", item_id="fc_1",
                        delta='"start_date":"2026-09-01","end_date":"2026-09-02"}'),
        SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=None)),
    ]
    model = OpenAIResponsesChatModel(api_key="x", model="test")
    model._client = _FakeClient(events)
    bound = model.bind_tools([_tool()], tool_choice="auto")

    msg = await bound.ainvoke([HumanMessage(content="xin nghỉ phép năm 1-2/9")])

    assert msg.tool_calls, "phải có tool_call"
    tc = msg.tool_calls[0]
    assert tc["name"] == "create_leave_request"
    assert tc["args"] == {
        "leave_type": "annual", "start_date": "2026-09-01", "end_date": "2026-09-02",
    }
    assert tc["id"] == "call_1"  # giữ call_id thật cho ToolMessage


@pytest.mark.asyncio
async def test_astream_args_done_fallback():
    """Chỉ có event 'done' (không delta) -> vẫn lấy được full arguments."""
    events = [
        SimpleNamespace(
            type="response.output_item.added",
            item=SimpleNamespace(type="function_call", id="fc_9", call_id="call_9",
                                 name="cancel_leave_request"),
        ),
        SimpleNamespace(type="response.function_call_arguments.done", item_id="fc_9",
                        arguments='{"request_id":"r-1"}'),
        SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=None)),
    ]
    model = OpenAIResponsesChatModel(api_key="x", model="test")
    model._client = _FakeClient(events)
    bound = model.bind_tools([_tool()], tool_choice="auto")
    msg = await bound.ainvoke([HumanMessage(content="hủy đơn r-1")])
    assert msg.tool_calls[0]["args"] == {"request_id": "r-1"}
