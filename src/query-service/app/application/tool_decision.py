from dataclasses import dataclass, field
from typing import Any

from app.application.hr_intents import HR_INTENTS


VALID_TOOL_NAMES = {"rag_search", "hr_query"}
VALID_HR_INTENTS = HR_INTENTS


@dataclass(frozen=True)
class ToolDecision:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


def normalize_tool_decision(decision: ToolDecision) -> ToolDecision:
    if decision.tool_name != "hr_query":
        return ToolDecision(tool_name="rag_search", arguments={}, reason="fallback to rag_search")

    intent = str(decision.arguments.get("intent", "")).strip()
    if intent not in VALID_HR_INTENTS:
        return ToolDecision(tool_name="rag_search", arguments={}, reason="invalid hr intent")

    return ToolDecision(
        tool_name="hr_query",
        arguments={"intent": intent},
        reason=decision.reason,
    )
