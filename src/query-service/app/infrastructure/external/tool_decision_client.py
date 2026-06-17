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
        if any(token in normalized for token in ["cham cong", "di muon", "di tre", "ngay cong", "attendance"]):
            return ToolDecision(tool_name="hr_query", arguments={"intent": "attendance"}, reason="mock attendance match")
        if any(token in normalized for token in ["phuc loi", "bao hiem", "phu cap", "benefits", "allowance"]):
            return ToolDecision(tool_name="hr_query", arguments={"intent": "benefits"}, reason="mock benefits match")
        if any(token in normalized for token in ["hieu suat", "danh gia", "kpi", "performance"]):
            return ToolDecision(tool_name="hr_query", arguments={"intent": "performance"}, reason="mock performance match")
        if any(token in normalized for token in ["onboarding cua toi", "tien do onboarding", "my onboarding"]):
            return ToolDecision(tool_name="hr_query", arguments={"intent": "onboarding"}, reason="mock onboarding match")
        return ToolDecision(tool_name="rag_search", arguments={}, reason="mock default rag")

    def reset(self) -> None:
        self._forced_decisions.clear()


class OpenAIToolDecisionClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI tool decisions")
        from app.infrastructure.external.routed_openai import build_routed_openai, route_model

        self._settings = settings
        # Route qua ai-router (chat.completions, capability `triage`) khi OPENAI_BASE_URL set.
        self._client, _ = build_routed_openai(settings)
        self._model = route_model(settings, settings.intent_capability, settings.openai_llm_model)

    async def choose_tool(
        self,
        question: str,
        recent_messages: list[tuple[str, str]],
        available_tools: Sequence[str],
    ) -> ToolDecision:
        # Use full discovered tool list; no longer restricted to VALID_TOOL_NAMES.
        all_tool_names = sorted(set(available_tools)) if available_tools else sorted(VALID_TOOL_NAMES)
        history = "\n".join(f"{role}: {content}" for role, content in recent_messages[-5:])
        tool_list_str = ", ".join(all_tool_names)
        from app.infrastructure.external.routed_openai import extract_json_text

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You route one internal chatbot question to exactly one tool. "
                            "Return only JSON: {\"tool_name\": \"<name>\", \"arguments\": {<args>}}. "
                            f"Available tools: {tool_list_str}. "
                            "Rules: use hr_query only for the current user's personal HR data "
                            "(leave balance / leave requests / attendance / personal onboarding / "
                            "payroll / benefits / performance) with argument {\"intent\": "
                            "\"leave_balance|leave_requests|attendance|onboarding|payroll|benefits|performance\"}. "
                            "Use rag_search for policies, procedures, internal documents, or unclear questions "
                            "(argument: {\"query\": \"<search query>\"}). "
                            "For any other listed tool, use its name and pass only the arguments it needs. "
                            "Never include user_id, document_ids, top_k, or authorization data in arguments."
                        ),
                    },
                    {"role": "user", "content": f"Recent messages:\n{history or '(empty)'}\n\nQuestion:\n{question}"},
                ],
                temperature=0,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"OpenAI tool decision unavailable: {exc}",
            ) from exc

        try:
            content = response.choices[0].message.content if response.choices else ""
            payload = json.loads(extract_json_text(content))
        except json.JSONDecodeError:
            return ToolDecision(tool_name="rag_search", arguments={}, reason="invalid JSON from model")

        tool_name = str(payload.get("tool_name", ""))
        arguments = payload.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}

        # Bespoke validation for known typed tools.
        if tool_name == "hr_query":
            intent = str(arguments.get("intent", ""))
            if intent in VALID_HR_INTENTS:
                return ToolDecision(
                    tool_name="hr_query",
                    arguments={"intent": intent},
                    reason="openai decision",
                )
            return ToolDecision(tool_name="rag_search", arguments={}, reason="invalid hr intent")

        if tool_name == "rag_search":
            return ToolDecision(
                tool_name="rag_search",
                arguments={"query": str(arguments.get("query", question))},
                reason="openai decision",
            )

        # Generic discovered tool: accept if it is in the available list.
        if tool_name in all_tool_names:
            return ToolDecision(
                tool_name=tool_name,
                arguments=arguments,
                reason="openai decision (generic tool)",
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
