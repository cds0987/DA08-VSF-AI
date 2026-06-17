"""LangChain BaseChatModel adapter cho OpenAI **Chat Completions** API (chuẩn portable).

Vì sao tồn tại: query-service trước dùng Responses API (OpenAI-only) -> KHÓA cứng provider,
không route qua ai-router (chỉ proxy /v1/chat/completions) -> không cân bằng key, không
fallback OpenRouter. Adapter này chuẩn hoá về chat.completions => chạy được với MỌI provider
OpenAI-compatible (OpenAI, ai-router, OpenRouter, vLLM...) qua `base_url`.

HỢP ĐỒNG BẮT BUỘC (graph + orchestration + Langfuse dựa vào — đừng phá, có test gác):
  1. ainvoke/astream -> AIMessage(.content, .tool_calls)            # route_after_think rẽ theo tool_calls
  2. bind_tools(tools, tool_choice=...) honor "auto"/"required"/"none"
  3. usage_metadata = {input_tokens, output_tokens, total_tokens, input_token_details:{cache_read}}
  4. response_metadata["model_name"] = MODEL THẬT provider/router trả (devops data-analysis)
  5. response_metadata["router"] = _router (key_id/tier...) nếu đi qua ai-router (drill-down Langfuse)
  6. _astream yield AIMessageChunk content delta (+ on_llm_new_token) rồi 1 chunk cuối mang
     tool_call_chunks (path tool) hoặc usage_metadata (path text).
  7. Không có SystemMessage -> tự chèn build_agent_system_prompt() (kèm NGÀY HÔM NAY) như
     adapter Responses cũ -> think_node KHÔNG mất system prompt khi đổi adapter.

Mọi đặc thù provider đóng kín trong file này; LangGraph/orchestration tuyệt đối không biết.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Iterator, Sequence, Union

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from openai import AsyncOpenAI

from app.application.prompts import build_agent_system_prompt

logger = logging.getLogger(__name__)


class OpenAIChatModel(BaseChatModel):
    """BaseChatModel bọc OpenAI Chat Completions. Tương thích .bind_tools()/.with_structured_output()."""

    api_key: str = ""
    base_url: str | None = None          # None -> OpenAI mặc định; set -> ai-router/provider khác
    model: str = "gpt-4o-mini"           # khi route qua ai-router: chuỗi này = CAPABILITY (think/triage/...)
    timeout: float = 30.0
    max_output_tokens: int = 2048
    temperature: float = 0.0

    _client: Any = None  # type: ignore[assignment]
    _bound_tools: Any = None  # type: ignore[assignment]
    _tool_choice: Any = None  # type: ignore[assignment]
    _response_format: Any = None  # type: ignore[assignment]

    @property
    def _llm_type(self) -> str:
        return "openai-chat-completions"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "temperature": self.temperature}

    @property
    def openai_client(self) -> AsyncOpenAI:
        if self._client is None:
            kwargs: dict[str, Any] = {"api_key": self.api_key, "timeout": self.timeout}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    # ----------------------------------------------------------------- messages
    def _to_chat_messages(self, messages: Sequence[BaseMessage]) -> list[dict]:
        """LangChain messages -> chat.completions messages (role-based, KHÔNG làm phẳng).

        Khác adapter Responses (ghép history thành 1 chuỗi): ở đây giữ đúng role +
        liên kết ToolMessage<->tool_call_id => model theo tool tốt hơn. Thiếu SystemMessage
        -> chèn build_agent_system_prompt() ở đầu (giữ hành vi think_node).
        """
        out: list[dict] = []
        has_system = False
        for msg in messages:
            if isinstance(msg, SystemMessage):
                out.append({"role": "system", "content": str(msg.content or "")})
                has_system = True
            elif isinstance(msg, HumanMessage):
                out.append({"role": "user", "content": str(msg.content or "")})
            elif isinstance(msg, AIMessage):
                m: dict[str, Any] = {"role": "assistant", "content": str(msg.content or "") or None}
                if msg.tool_calls:
                    m["tool_calls"] = [
                        {
                            "id": tc.get("id") or f"call_{tc['name']}",
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc.get("args", {}), ensure_ascii=False),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                out.append(m)
            elif isinstance(msg, ToolMessage):
                out.append({
                    "role": "tool",
                    "tool_call_id": getattr(msg, "tool_call_id", "") or "",
                    "content": str(msg.content or ""),
                })
        if not has_system:
            out.insert(0, {"role": "system", "content": build_agent_system_prompt()})
        return out

    def _tools_schema(self, tools: Sequence[BaseTool | dict]) -> list[dict]:
        """LangChain tools -> chat.completions tool schema {type:function, function:{...}}.

        Chấp nhận cả dict (MCP-discovered) dạng phẳng {name,...} hoặc đã nested {function:{...}}.
        """
        from langchain_core.utils.function_calling import convert_to_openai_function

        result: list[dict] = []
        for t in tools:
            if isinstance(t, dict):
                if "function" in t:                      # đã đúng dạng chat.completions
                    result.append(t)
                elif "name" in t:                        # dạng phẳng (Responses) -> bọc lại
                    result.append({"type": "function", "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                    }})
                continue
            try:
                fn = convert_to_openai_function(t)       # {name, description, parameters}
                result.append({"type": "function", "function": fn})
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("tools_schema_convert_failed for %s: %s", getattr(t, "name", "?"), exc)
                result.append({"type": "function", "function": {
                    "name": getattr(t, "name", "unnamed"),
                    "description": getattr(t, "description", ""),
                    "parameters": {"type": "object", "properties": {}},
                }})
        return result

    def _build_params(self, messages: Sequence[BaseMessage]) -> dict:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_chat_messages(messages),
            "max_completion_tokens": self.max_output_tokens,
            "temperature": self.temperature,
        }
        if self._bound_tools:
            params["tools"] = self._bound_tools
            if self._tool_choice:
                params["tool_choice"] = self._tool_choice
        if self._response_format:
            params["response_format"] = self._response_format
        return params

    # ----------------------------------------------------------------- usage/parse
    @staticmethod
    def _usage_metadata(usage: Any) -> dict | None:
        """chat.completions usage -> LangChain usage_metadata (shape KHỚP adapter Responses)."""
        if usage is None:
            return None
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or (input_tokens + output_tokens))
        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total,
            "input_token_details": {"cache_read": cached},
        }

    def _response_meta(self, real_model: str | None, raw: Any) -> dict:
        """response_metadata: model THẬT + _router (nếu qua ai-router) cho devops/Langfuse."""
        meta: dict[str, Any] = {"model_name": real_model or self.model}
        router = None
        extra = getattr(raw, "model_extra", None)
        if isinstance(extra, dict):
            router = extra.get("_router")
        if router:
            meta["router"] = router      # {key_id, provider, model, tier, endpoint}
        return meta

    def _parse_response(self, resp: Any) -> AIMessage:
        choice = (resp.choices or [None])[0]
        msg = getattr(choice, "message", None) if choice else None
        content = (getattr(msg, "content", "") or "") if msg else ""
        tool_calls: list[dict] = []
        for tc in (getattr(msg, "tool_calls", None) or []) if msg else []:
            fn = getattr(tc, "function", None)
            args_str = getattr(fn, "arguments", "") or "{}"
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({
                "name": getattr(fn, "name", "") or "",
                "args": args,
                "id": getattr(tc, "id", "") or "",
                "type": "tool_call",
            })
        extra: dict[str, Any] = {"response_metadata": self._response_meta(getattr(resp, "model", None), resp)}
        um = self._usage_metadata(getattr(resp, "usage", None))
        if um is not None:
            extra["usage_metadata"] = um
        if tool_calls:
            return AIMessage(content=content, tool_calls=tool_calls, **extra)
        return AIMessage(content=content, **extra)

    # ----------------------------------------------------------------- BaseChatModel
    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, **kwargs) -> ChatResult:
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        resp = loop.run_until_complete(self.openai_client.chat.completions.create(**self._build_params(messages)))
        return ChatResult(generations=[ChatGeneration(message=self._parse_response(resp))])

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None, **kwargs) -> ChatResult:
        resp = await self.openai_client.chat.completions.create(**self._build_params(list(messages)))
        return ChatResult(generations=[ChatGeneration(message=self._parse_response(resp))])

    def _should_stream(self, *, async_api: bool = False, run_manager: Any = None, **kwargs) -> bool:  # type: ignore[override]
        if self._streaming_disabled(**kwargs):
            return False
        return async_api

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs,
    ) -> AsyncIterator[Any]:
        """Stream chat.completions -> ChatGenerationChunk. Gom tool_calls theo `index`."""
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        params = self._build_params(list(messages))
        params["stream"] = True
        params["stream_options"] = {"include_usage": True}

        fn_calls: dict[int, dict] = {}        # index -> {id, name, args_buf}
        fn_order: list[int] = []
        real_model: str | None = None
        router_meta: Any = None
        usage_meta: dict | None = None
        yielded = False

        stream = await self.openai_client.chat.completions.create(**params)
        async for chunk in stream:
            if real_model is None:
                real_model = getattr(chunk, "model", None)
            extra = getattr(chunk, "model_extra", None)
            if router_meta is None and isinstance(extra, dict):
                router_meta = extra.get("_router")
            if getattr(chunk, "usage", None) is not None:
                usage_meta = self._usage_metadata(chunk.usage)

            choice = (chunk.choices or [None])[0]
            delta = getattr(choice, "delta", None) if choice else None
            if delta is None:
                continue

            text = getattr(delta, "content", None)
            if text:
                gen = ChatGenerationChunk(message=AIMessageChunk(content=text))
                if run_manager is not None:
                    await run_manager.on_llm_new_token(text, chunk=gen)
                yield gen
                yielded = True

            for tc in (getattr(delta, "tool_calls", None) or []):
                idx = getattr(tc, "index", 0) or 0
                slot = fn_calls.get(idx)
                if slot is None:
                    slot = {"id": "", "name": "", "args_buf": []}
                    fn_calls[idx] = slot
                    fn_order.append(idx)
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["args_buf"].append(fn.arguments)

        meta = self._response_meta_from_stream(real_model, router_meta)
        if fn_calls:
            tool_call_chunks = [
                {
                    "name": fn_calls[i]["name"],
                    "args": "".join(fn_calls[i]["args_buf"]),
                    "id": fn_calls[i]["id"] or f"call_{fn_calls[i]['name']}",
                    "index": pos,
                }
                for pos, i in enumerate(fn_order)
            ]
            extra_kw: dict[str, Any] = {"response_metadata": meta}
            if usage_meta is not None:
                extra_kw["usage_metadata"] = usage_meta
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=tool_call_chunks, **extra_kw))
            yielded = True
        elif usage_meta is not None:
            yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=usage_meta, response_metadata=meta))
            yielded = True

        if not yielded:
            yield ChatGenerationChunk(message=AIMessageChunk(content=""))

    def _response_meta_from_stream(self, real_model: str | None, router_meta: Any) -> dict:
        meta: dict[str, Any] = {"model_name": real_model or self.model}
        if router_meta:
            meta["router"] = router_meta
        return meta

    # ----------------------------------------------------------------- bind/struct
    def invoke(self, input: Union[Sequence[BaseMessage], str], **kwargs) -> AIMessage:
        messages = [HumanMessage(content=input)] if isinstance(input, str) else list(input)
        result = self._generate(messages)
        return result.generations[0].message  # type: ignore[return-value]

    def bind_tools(self, tools: Sequence[BaseTool | dict], **kwargs) -> "OpenAIChatModel":
        bound = self.copy()
        bound._bound_tools = self._tools_schema(tools)  # type: ignore[attr-defined]
        bound._tool_choice = kwargs.get("tool_choice")  # type: ignore[attr-defined]
        return bound

    def with_structured_output(self, schema: type | dict, **kwargs) -> "OpenAIChatModel":
        if isinstance(schema, type):
            json_schema = schema.model_json_schema()
            schema_name = getattr(schema, "__name__", "Answer")
        else:
            json_schema = schema
            schema_name = json_schema.get("name", "Answer")
        bound = self.copy()
        bound._response_format = {  # type: ignore[attr-defined]
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": json_schema},
        }
        return bound

    def stream(self, input: Union[Sequence[BaseMessage], str], **kwargs) -> Iterator[AIMessage]:
        # Sync stream hiếm dùng (LangGraph async). Trả 1 phát non-stream cho đơn giản+đúng.
        yield self.invoke(input, **kwargs)
