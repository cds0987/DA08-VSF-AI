"""
LangChain BaseChatModel adapter for OpenAI Responses API.

This adapter bridges the existing OpenAI Responses API usage with LangGraph's
BaseChatModel interface. It allows LangGraph's .bind_tools() and
.with_structured_output() to work with the OpenAI Responses API.

Key translation:
  LangGraph/LC  ->  Responses API:
    .invoke([HumanMessage])           -> client.responses.create(input=..., instructions=...)
    .bind_tools([BaseTool])           -> serializes to OpenAI function tool schema
    .with_structured_output(S)         -> uses response_format with json_schema
    .stream(input)                     -> streams response tokens

  Responses API  ->  LangGraph/LC:
    function_call output item          -> AIMessage.tool_calls
    output_text                        -> AIMessage.content
"""

import json
import logging
from typing import Any, Iterator, Sequence, Union

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field
from openai import AsyncOpenAI

from app.application.prompts import AGENT_SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class OpenAIResponsesChatModel(BaseChatModel):
    """
    LangChain BaseChatModel that wraps OpenAI Responses API.

    Compatible with LangGraph's .bind_tools() and .with_structured_output()
    methods, enabling full LangGraph ReAct agent support.
    """

    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout: float = 30.0
    max_output_tokens: int = 2048
    temperature: float = 0.0

    _client: Any = None  # type: ignore[assignment]
    _bound_tools: Any = None  # type: ignore[assignment]
    _tool_choice: Any = None  # type: ignore[assignment]
    _response_format: Any = None  # type: ignore[assignment]

    @property
    def _llm_type(self) -> str:
        return "openai-responses"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "temperature": self.temperature}

    @property
    def openai_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client

    @staticmethod
    def _split_system(messages: Sequence[BaseMessage]) -> tuple[str | None, list[BaseMessage]]:
        """
        Extract the *last* SystemMessage from a message list.

        Returns (system_content, remaining_messages) so the caller can use
        system_content as the `instructions` parameter of the Responses API
        without also including it in the `input` text.
        """
        system_content: str | None = None
        rest: list[BaseMessage] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_content = str(msg.content or "")
            else:
                rest.append(msg)
        return system_content, rest

    def _format_messages(self, messages: Sequence[BaseMessage]) -> str:
        """Convert LangChain messages (no SystemMessage) to a string input for Responses API."""
        parts: list[str] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                # SystemMessage is passed as `instructions`, not as conversational input.
                continue
            elif isinstance(msg, HumanMessage):
                parts.append(f"Nguoi dung: {msg.content}")
            elif isinstance(msg, AIMessage):
                if msg.tool_calls:
                    calls_str = ", ".join(
                        f"{tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})"
                        for tc in msg.tool_calls
                    )
                    parts.append(f"Assistant (da goi tool): {calls_str}")
                if msg.content:
                    parts.append(f"Assistant: {msg.content}")
            elif isinstance(msg, ToolMessage):
                tool_label = msg.name or "tool"
                parts.append(f"[{tool_label} result]: {msg.content}")
        return "\n\n".join(parts) if parts else "Tong dai"

    def _bind_tools_schema(self, tools: Sequence[BaseTool | dict]) -> list[dict]:
        """Convert LangChain tools to OpenAI Responses API function tool schema.

        Responses API wants the flat form {type, name, description, parameters}.
        For BaseTool objects we delegate to convert_to_openai_function so the
        args_schema (e.g. rag_search's required `query`) is serialised correctly —
        the previous code read the wrong attribute (`t.schema`, a bound pydantic
        method) and emitted `parameters: {}`, so the model never saw the `query`
        param and called rag_search with an empty query → 0 relevant chunks.
        """
        from langchain_core.utils.function_calling import convert_to_openai_function

        result = []
        for t in tools:
            if isinstance(t, dict):
                result.append(t)
                continue
            try:
                fn = convert_to_openai_function(t)  # {name, description, parameters}
                result.append({"type": "function", **fn})
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.warning("bind_tools_schema_convert_failed for %s: %s", getattr(t, "name", "?"), exc)
                result.append({
                    "type": "function",
                    "name": getattr(t, "name", "unnamed"),
                    "description": getattr(t, "description", ""),
                    "parameters": {"type": "object", "properties": {}},
                })
        return result

    def _build_params(self, messages: Sequence[BaseMessage]) -> dict:
        """
        Build params dict for responses.create().

        If the message list contains a SystemMessage, use its content as the
        `instructions` (e.g. TRIAGE_SYSTEM_PROMPT for triage_node).
        Otherwise fall back to DEFAULT_SYSTEM_PROMPT (AGENT_SYSTEM_PROMPT for think_node).
        """
        system_content, rest = self._split_system(messages)
        params: dict = {
            "model": self.model,
            "instructions": system_content if system_content is not None else DEFAULT_SYSTEM_PROMPT,
            "input": self._format_messages(rest),
            "max_output_tokens": self.max_output_tokens,
            "timeout": self.timeout,
            "temperature": self.temperature,
        }
        if self._bound_tools:
            params["tools"] = self._bound_tools
            # tool_choice ("auto" | "required" | "none") is only meaningful when
            # tools are present. think_node forces "required" on the first ReAct
            # iteration so gpt-4o-mini cannot short-circuit to a "no info" answer
            # without first calling rag_search/hr_query.
            if self._tool_choice:
                params["tool_choice"] = self._tool_choice
        if self._response_format:
            params["response_format"] = self._response_format
        return params

    def _invoke_sync(self, messages: Sequence[BaseMessage]) -> Any:
        """Synchronous wrapper around the async Responses API call."""
        import asyncio
        params = self._build_params(messages)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.openai_client.responses.create(**params))

    def _parse_response(self, response) -> AIMessage:
        """Parse OpenAI Responses API response → LangChain AIMessage."""
        content_parts: list[str] = []
        tool_calls: list[dict] = []

        output_items = getattr(response, "output", []) or []

        for item in output_items:
            item_type = getattr(item, "type", None)

            if item_type == "message":
                text_items = getattr(item, "content", []) or []
                for chunk in text_items:
                    if getattr(chunk, "type", None) == "output_text":
                        content_parts.append(getattr(chunk, "text", ""))

            elif item_type == "function_call":
                name = getattr(item, "name", "") or ""
                args_str = getattr(item, "arguments", "") or "{}"
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({
                    "name": name,
                    "args": args,
                    "id": getattr(item, "call_id", f"call_{name}"),
                    "type": "tool_call",
                })

        content = "".join(content_parts)

        if tool_calls:
            return AIMessage(content=content, tool_calls=tool_calls)
        return AIMessage(content=content)

    # -------------------------------------------------------------------------
    # LangChain BaseChatModel interface methods
    # -------------------------------------------------------------------------

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs,
    ) -> ChatResult:
        """Required by BaseChatModel abstract class. Delegates to invoke()."""
        ai_msg = self.invoke(messages, **kwargs)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs,
    ) -> ChatResult:
        """Async generation — required for LangGraph async nodes with ainvoke()."""
        params = self._build_params(list(messages))
        response = await self.openai_client.responses.create(**params)
        ai_msg = self._parse_response(response)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    def invoke(
        self,
        input: Union[Sequence[BaseMessage], str],
        **kwargs,
    ) -> AIMessage:
        """Synchronous invoke — used by LangGraph nodes."""
        if isinstance(input, str):
            messages = [HumanMessage(content=input)]
        else:
            messages = list(input)
        response = self._invoke_sync(messages)
        return self._parse_response(response)

    def bind_tools(
        self,
        tools: Sequence[BaseTool | dict],
        **kwargs,
    ) -> "OpenAIResponsesChatModel":
        """
        Bind tools to the model. Returns a new model instance with tools bound.
        When .invoke() is called, the tools are serialized and passed to the API.
        """
        bound = self.copy()
        bound._bound_tools = self._bind_tools_schema(tools)  # type: ignore[attr-defined]
        # Honor tool_choice (previously dropped silently). OpenAI Responses API
        # accepts "auto" | "required" | "none" | {"type":"function","name":...}.
        bound._tool_choice = kwargs.get("tool_choice")  # type: ignore[attr-defined]
        return bound

    def with_structured_output(
        self,
        schema: type | dict,
        **kwargs,
    ) -> "OpenAIResponsesChatModel":
        """
        Bind a structured output schema. Returns a model that produces a
        Pydantic/model instance from .invoke().
        """
        if isinstance(schema, type):
            json_schema = schema.model_json_schema()
            schema_name = getattr(schema, "__name__", "Answer")
        else:
            json_schema = schema
            schema_name = json_schema.get("name", "Answer")

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": json_schema,
            },
        }
        bound = self.copy()
        bound._response_format = response_format  # type: ignore[attr-defined]
        return bound

    def stream(
        self,
        input: Union[Sequence[BaseMessage], str],
        **kwargs,
    ) -> Iterator[AIMessage]:
        """
        Streaming invoke — yields tokens as AIMessage chunks.
        Used by LangGraph for token-level SSE streaming.
        """
        if isinstance(input, str):
            messages = [HumanMessage(content=input)]
        else:
            messages = list(input)

        params = self._build_params(messages)
        params["stream"] = True
        response = self.openai_client.responses.create(**params)

        for event in response:
            event_type = getattr(event, "type", None)
            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "") or ""
                if delta:
                    yield AIMessage(content=delta)
