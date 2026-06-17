"""HỢP ĐỒNG adapter chat.completions (OpenAIChatModel) — graph/orchestration/Langfuse dựa vào.

Đây là TEST GÁC: dev sau sửa adapter mà phá 1 trong các bất biến dưới -> CI đỏ -> không lên
prod. Các bất biến: tool_calls parse đúng, usage_metadata đúng shape, response_metadata.model_name
= MODEL THẬT (không phải capability gửi đi), _router surface được, system prompt tự chèn, stream
gọi on_llm_new_token.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.infrastructure.external.langchain_chat_adapter import OpenAIChatModel


# ----------------------------------------------------------------- fakes
def _chunk(*, content=None, tool_calls=None, usage=None, model="gpt-REAL", router=None):
    choice = SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls))
    return SimpleNamespace(model=model, model_extra=({"_router": router} if router else {}),
                           usage=usage, choices=[choice])


def _tc(index, id_, name, args):
    return SimpleNamespace(index=index, id=id_, type="function",
                           function=SimpleNamespace(name=name, arguments=args))


class _FakeCompletions:
    def __init__(self, chunks):
        self._chunks = chunks

    async def create(self, **kwargs):
        assert kwargs.get("stream") is True, "ainvoke phải đi qua _astream (stream=True)"
        chunks = self._chunks

        async def _gen():
            for c in chunks:
                yield c

        return _gen()


class _FakeClient:
    def __init__(self, chunks):
        self.chat = SimpleNamespace(completions=_FakeCompletions(chunks))


def _model(chunks, **kw):
    m = OpenAIChatModel(api_key="x", model="think", **kw)
    m._client = _FakeClient(chunks)
    return m


class _Input(BaseModel):
    query: str = Field(description="truy vấn")


def _rag_tool():
    async def _run(**kw):
        return "ctx"
    return StructuredTool.from_function(coroutine=_run, name="rag_search",
                                        description="tìm tài liệu", args_schema=_Input)


# ----------------------------------------------------------------- contract tests
@pytest.mark.asyncio
async def test_text_answer_usage_and_real_model():
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=3))
    chunks = [
        _chunk(content="Chào ", model="gpt-5.4-mini"),
        _chunk(content="bạn", model="gpt-5.4-mini"),
        _chunk(usage=usage, model="gpt-5.4-mini", router={"key_id": "oai-3", "tier": "free_oai"}),
    ]
    msg = await _model(chunks).ainvoke([HumanMessage(content="hi")])

    assert msg.content == "Chào bạn"
    # usage_metadata ĐÚNG SHAPE orchestration + Langfuse cần
    assert msg.usage_metadata["input_tokens"] == 10
    assert msg.usage_metadata["output_tokens"] == 5
    assert msg.usage_metadata["input_token_details"]["cache_read"] == 3
    # model THẬT (provider trả), KHÔNG phải capability "think" gửi đi -> devops data-analysis
    assert msg.response_metadata["model_name"] == "gpt-5.4-mini"
    # _router surface cho Langfuse drill-down per-key
    assert msg.response_metadata["router"]["key_id"] == "oai-3"


@pytest.mark.asyncio
async def test_tool_call_parsed_and_routed():
    # tool args đến theo nhiều delta -> phải gom theo index
    chunks = [
        _chunk(tool_calls=[_tc(0, "call_1", "rag_search", '{"query":')]),
        _chunk(tool_calls=[_tc(0, None, None, '"nghỉ phép"}')]),
        _chunk(usage=SimpleNamespace(prompt_tokens=8, completion_tokens=2, total_tokens=10,
                                     prompt_tokens_details=None)),
    ]
    bound = _model(chunks).bind_tools([_rag_tool()], tool_choice="auto")
    msg = await bound.ainvoke([HumanMessage(content="chính sách nghỉ phép?")])

    assert msg.tool_calls, "phải có tool_call -> route_after_think rẽ act_node"
    tc = msg.tool_calls[0]
    assert tc["name"] == "rag_search"
    assert tc["args"] == {"query": "nghỉ phép"}
    assert tc["id"] == "call_1"


@pytest.mark.asyncio
async def test_on_llm_new_token_called_for_sse():
    """Token phải đẩy qua on_llm_new_token -> orchestration on_chat_model_stream -> SSE."""
    seen: list[str] = []

    class _RM:
        async def on_llm_new_token(self, token, chunk=None):
            seen.append(token)

    model = _model([_chunk(content="a"), _chunk(content="b"),
                    _chunk(usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1,
                                                 total_tokens=2, prompt_tokens_details=None))])
    out = [c async for c in model._astream([HumanMessage(content="x")], run_manager=_RM())]
    assert seen == ["a", "b"]
    assert out, "phải yield ít nhất 1 chunk"


def test_system_prompt_auto_injected_when_absent():
    """think_node KHÔNG truyền SystemMessage -> adapter PHẢI tự chèn agent prompt (kèm ngày)."""
    msgs = OpenAIChatModel(api_key="x", model="think")._to_chat_messages([HumanMessage(content="hi")])
    assert msgs[0]["role"] == "system"
    assert "CONTEXT" in msgs[0]["content"]      # build_agent_system_prompt chèn '== CONTEXT =='


def test_system_prompt_not_double_injected():
    """triage_node truyền SystemMessage -> dùng nguyên, KHÔNG chèn thêm."""
    msgs = OpenAIChatModel(api_key="x", model="triage")._to_chat_messages(
        [SystemMessage(content="TRIAGE"), HumanMessage(content="hi")]
    )
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == "TRIAGE"


def test_tool_schema_is_chat_completions_nested_form():
    """chat.completions cần {type:function, function:{...}} (KHÁC Responses phẳng)."""
    schema = OpenAIChatModel(api_key="x", model="think")._tools_schema([_rag_tool()])
    assert schema[0]["type"] == "function"
    assert schema[0]["function"]["name"] == "rag_search"
    assert "query" in schema[0]["function"]["parameters"]["properties"]


def test_base_url_injected_into_client():
    """OPENAI_BASE_URL set -> client phải trỏ router (nếu không = bỏ qua router, mất cân bằng key)."""
    m = OpenAIChatModel(api_key="tok", base_url="http://ai-router:8010/v1", model="think")
    assert m.openai_client.base_url.host == "ai-router"
