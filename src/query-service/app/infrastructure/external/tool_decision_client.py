from collections.abc import Sequence
import json
import re
import unicodedata
import warnings

from fastapi import HTTPException, status

from app.application.tool_decision import ToolDecision, VALID_HR_INTENTS, VALID_TOOL_NAMES
from app.infrastructure.config import Settings

warnings.warn(
    "OpenAIToolDecisionClient and MockToolDecisionClient are deprecated. "
    "Use QueryAgentLoop with AGENT_MODE=react for true agentic behavior. "
    "These classes will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2,
)


class MockToolDecisionClient:
    def __init__(self) -> None:
        self._forced_decisions: list[ToolDecision] = []

    def force_next_decision(self, decision: ToolDecision) -> None:
        self._forced_decisions.append(decision)

    async def choose_tool(
        self,
        question: str,
        recent_messages: list[tuple[str, str]],
        available_tools: Sequence[str],
    ) -> ToolDecision:
        if self._forced_decisions:
            return self._forced_decisions.pop(0)

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
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI tool decisions")
        from openai import AsyncOpenAI

        self._settings = settings
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


def _normalize_text(text: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(character)
    )
    without_punctuation = re.sub(r"[_\W]+", " ", without_accents, flags=re.UNICODE)
    return re.sub(r"\s+", " ", without_punctuation).strip()
