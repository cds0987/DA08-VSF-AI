from collections.abc import Sequence
import json
import re
import unicodedata
from typing import Any

from fastapi import HTTPException, status

from app.application.ports import MCPToolClient, ToolSpec
from app.application.tool_decision import ToolDecision, VALID_HR_INTENTS, VALID_TOOL_NAMES
from app.infrastructure.config import Settings


class MockToolDecisionClient:
    def __init__(self, settings: Settings, mcp_client: MCPToolClient) -> None:
        self._settings = settings
        self._mcp_client = mcp_client
        self._forced_decisions: list[ToolDecision] = []

    def force_next_decision(self, decision: ToolDecision) -> None:
        self._forced_decisions.append(decision)

    async def choose_tool(
        self,
        question: str,
        recent_messages: list[tuple[str, str]],
        available_tools: Sequence[str],
    ) -> ToolDecision:
        del recent_messages
        if self._forced_decisions:
            return self._forced_decisions.pop(0)

        if self._settings.tool_routing_mode.strip().lower() == "native":
            specs = await self._mcp_client.list_tool_specs()
            return _choose_mock_native(question, specs)

        normalized = _normalize_text(question)
        if any(token in normalized for token in ["luong", "payroll", "phieu luong", "salary", "gross salary"]):
            return ToolDecision(tool_name="hr_query", arguments={"intent": "payroll"}, reason="mock payroll match")
        if any(token in normalized for token in ["don nghi", "leave request", "trang thai nghi", "leave status"]):
            return ToolDecision(
                tool_name="hr_query",
                arguments={"intent": "leave_requests"},
                reason="mock leave request match",
            )
        if any(
            token in normalized
            for token in ["ngay nghi", "nghi phep con", "leave balance", "pto balance", "remaining leave"]
        ):
            return ToolDecision(
                tool_name="hr_query",
                arguments={"intent": "leave_balance"},
                reason="mock leave balance match",
            )
        return ToolDecision(tool_name="rag_search", arguments={}, reason="mock default rag")

    def reset(self) -> None:
        self._forced_decisions.clear()


class OpenAIToolDecisionClient:
    def __init__(self, settings: Settings, mcp_client: MCPToolClient) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI tool decisions")
        from openai import AsyncOpenAI

        self._settings = settings
        self._mcp_client = mcp_client
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
        )

    async def choose_tool(
        self,
        question: str,
        recent_messages: list[tuple[str, str]],
        available_tools: Sequence[str],
    ) -> ToolDecision:
        if self._settings.tool_routing_mode.strip().lower() == "native":
            return await self._choose_tool_native(question, recent_messages)

        allowed_tools = sorted(set(available_tools) & VALID_TOOL_NAMES)
        history = "\n".join(f"{role}: {content}" for role, content in recent_messages[-5:])
        try:
            response = await self._client.responses.create(
                model=self._settings.openai_llm_model,
                instructions=(
                    "You route one internal chatbot question to exactly one tool. "
                    "Return only JSON. Valid shapes are "
                    '{"tool_name":"rag_search","arguments":{}} or '
                    '{"tool_name":"hr_query","arguments":{"intent":"leave_balance|leave_requests|payroll"}}. '
                    f"Available tools: {', '.join(allowed_tools)}. "
                    "Use hr_query only for the current user's personal HR data: leave balance, leave requests, "
                    "or payroll. Use rag_search for policies, procedures, internal documents, or unclear questions. "
                    "Never include user_id, document_ids, top_k, or authorization data."
                ),
                input=f"Recent messages:\n{history or '(empty)'}\n\nQuestion:\n{question}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"OpenAI tool decision unavailable: {exc}",
            ) from exc

        try:
            payload = json.loads(getattr(response, "output_text", "") or "{}")
        except json.JSONDecodeError:
            return ToolDecision(tool_name="rag_search", arguments={}, reason="invalid JSON from model")

        tool_name = str(payload.get("tool_name", ""))
        arguments = payload.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        if tool_name == "hr_query" and str(arguments.get("intent", "")) in VALID_HR_INTENTS:
            return ToolDecision(
                tool_name="hr_query",
                arguments={"intent": str(arguments["intent"])},
                reason="openai decision",
            )
        return ToolDecision(tool_name="rag_search", arguments={}, reason="openai decision fallback")

    async def _choose_tool_native(
        self,
        question: str,
        recent_messages: list[tuple[str, str]],
    ) -> ToolDecision:
        specs = await self._mcp_client.list_tool_specs()
        if not specs:
            return ToolDecision(tool_name="rag_search", arguments={}, reason="no tool specs available")
        model_visible_tools = [
            {
                "type": "function",
                "name": spec.name,
                "description": spec.description,
                "parameters": _model_visible_schema(spec.input_schema),
            }
            for spec in specs
        ]
        history = "\n".join(f"{role}: {content}" for role, content in recent_messages[-5:])
        try:
            response = await self._client.responses.create(
                model=self._settings.openai_llm_model,
                instructions=(
                    "Choose exactly one tool for the user's question. "
                    "Use only the provided function tools. "
                    "Never invent authorization, user_id, document_ids, or top_k."
                ),
                input=f"Recent messages:\n{history or '(empty)'}\n\nQuestion:\n{question}",
                tools=model_visible_tools,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"OpenAI tool decision unavailable: {exc}",
            ) from exc

        tool_name, arguments = _native_response_selection(response)
        if not tool_name:
            return ToolDecision(tool_name="rag_search", arguments={}, reason="native decision fallback")
        spec_by_name = {spec.name: spec for spec in specs}
        spec = spec_by_name.get(tool_name)
        if spec is None:
            return ToolDecision(tool_name="rag_search", arguments={}, reason="unknown native tool")
        if not _arguments_match_schema(arguments, _model_visible_schema(spec.input_schema)):
            return ToolDecision(tool_name="rag_search", arguments={}, reason="invalid native arguments")
        return ToolDecision(tool_name=tool_name, arguments=arguments, reason="openai native decision")


def _choose_mock_native(question: str, specs: list[ToolSpec]) -> ToolDecision:
    spec_by_name = {spec.name: spec for spec in specs}
    normalized = _normalize_text(question)
    if "hr_query" in spec_by_name:
        if any(token in normalized for token in ["luong", "payroll", "phieu luong", "salary", "gross salary"]):
            return ToolDecision(tool_name="hr_query", arguments={"intent": "payroll"}, reason="mock native payroll")
        if any(token in normalized for token in ["don nghi", "leave request", "trang thai nghi", "leave status"]):
            return ToolDecision(tool_name="hr_query", arguments={"intent": "leave_requests"}, reason="mock native leave requests")
        if any(token in normalized for token in ["ngay nghi", "nghi phep con", "leave balance", "pto balance", "remaining leave"]):
            return ToolDecision(tool_name="hr_query", arguments={"intent": "leave_balance"}, reason="mock native leave balance")
    if "rag_search" in spec_by_name:
        return ToolDecision(tool_name="rag_search", arguments={"query": question}, reason="mock native default rag")
    first_tool = specs[0]
    return ToolDecision(tool_name=first_tool.name, arguments={}, reason="mock native first tool")


def _model_visible_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if not schema:
        return {"type": "object", "properties": {}}
    reserved = {"user_id", "document_ids", "top_k"}
    properties = dict(schema.get("properties") or {})
    visible_properties = {
        name: value
        for name, value in properties.items()
        if name not in reserved
    }
    required = [
        name
        for name in list(schema.get("required") or [])
        if name not in reserved
    ]
    model_schema = dict(schema)
    model_schema["properties"] = visible_properties
    if required:
        model_schema["required"] = required
    else:
        model_schema.pop("required", None)
    return model_schema


def _native_response_selection(response: Any) -> tuple[str, dict[str, Any]]:
    output = getattr(response, "output", None) or []
    for item in output:
        if getattr(item, "type", None) != "function_call":
            continue
        name = str(getattr(item, "name", "") or "")
        arguments = getattr(item, "arguments", {}) or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if isinstance(arguments, dict):
            return name, arguments
    return "", {}


def _arguments_match_schema(arguments: dict[str, Any], schema: dict[str, Any]) -> bool:
    if not isinstance(arguments, dict):
        return False
    properties = schema.get("properties") or {}
    required = list(schema.get("required") or [])
    for name in required:
        if name not in arguments:
            return False
    for name, value in arguments.items():
        spec = properties.get(name)
        if spec is None:
            continue
        expected_type = spec.get("type")
        if expected_type == "string" and not isinstance(value, str):
            return False
        if expected_type == "integer" and not isinstance(value, int):
            return False
        if expected_type == "array" and not isinstance(value, list):
            return False
        enum_values = spec.get("enum")
        if enum_values and value not in enum_values:
            return False
    return True


def _normalize_text(text: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(character)
    )
    without_punctuation = re.sub(r"[_\W]+", " ", without_accents, flags=re.UNICODE)
    return re.sub(r"\s+", " ", without_punctuation).strip()
