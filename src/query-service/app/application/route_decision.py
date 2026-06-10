from dataclasses import dataclass, field
from typing import Any

from app.application.tool_decision import ToolDecision
from app.domain.outcome import Outcome


VALID_ROUTE_DECISIONS = {
    "clarification",
    "identity_shortcut",
    "rag_search",
    "hr_query",
    "out_of_scope",
}

# Decisions that are handled by shortcut / LLM-generated responses (not tools).
_NON_TOOL_DECISIONS = {"clarification", "identity_shortcut", "out_of_scope", "off_topic"}

VALID_HR_INTENTS = {"leave_balance", "leave_requests", "payroll"}


@dataclass(frozen=True)
class RouteDecision:
    decision: str
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    direct_response: str | None = None
    reason: str = ""
    confidence: float = 0.0
    outcome: Outcome = Outcome.SUCCESS


def coerce_route_decision(
    decision: RouteDecision | ToolDecision,
    *,
    default_query: str,
    discovered_tools: set[str] | None = None,
) -> RouteDecision:
    if isinstance(decision, ToolDecision):
        return _from_legacy_tool_decision(
            decision, default_query=default_query, discovered_tools=discovered_tools
        )
    return normalize_route_decision(
        decision, default_query=default_query, discovered_tools=discovered_tools
    )


def normalize_route_decision(
    decision: RouteDecision,
    *,
    default_query: str,
    discovered_tools: set[str] | None = None,
) -> RouteDecision:
    route_name = str(decision.decision).strip()
    confidence = min(1.0, max(0.0, float(decision.confidence)))
    reason = decision.reason

    if route_name == "hr_query":
        intent = str(decision.tool_arguments.get("intent", "")).strip()
        if intent in VALID_HR_INTENTS:
            return RouteDecision(
                decision="hr_query",
                tool_arguments={"intent": intent},
                reason=reason,
                confidence=confidence,
                outcome=Outcome.SUCCESS,
            )
        return RouteDecision(
            decision="rag_search",
            tool_arguments={"query": default_query},
            reason="invalid hr intent",
            confidence=0.0,
            outcome=Outcome.REFUSE,
        )

    if route_name == "rag_search":
        query = str(decision.tool_arguments.get("query") or default_query).strip() or default_query
        return RouteDecision(
            decision="rag_search",
            tool_arguments={"query": query},
            reason=reason,
            confidence=confidence,
            outcome=Outcome.SUCCESS,
        )

    if route_name in {"clarification", "identity_shortcut", "out_of_scope"}:
        direct_response = str(decision.direct_response or "").strip()
        if not direct_response:
            return RouteDecision(
                decision="clarification",
                direct_response="Minh chua du ngu canh de tra loi. Ban vui long noi ro hon giup minh.",
                reason="missing direct response",
                confidence=0.0,
                outcome=Outcome.CLARIFY,
            )
        outcome_map = {
            "clarification": Outcome.CLARIFY,
            "identity_shortcut": Outcome.SUCCESS,
            "out_of_scope": Outcome.REFUSE,
        }
        return RouteDecision(
            decision=route_name,
            direct_response=direct_response,
            reason=reason,
            confidence=confidence,
            outcome=outcome_map[route_name],
        )

    if route_name == "off_topic":
        return RouteDecision(
            decision="off_topic",
            direct_response=(
                "Câu hỏi của bạn nằm ngoài phạm vi hệ thống HR và tài liệu nội bộ. "
                "Tôi chỉ hỗ trợ về chính sách công ty, HR và thông tin nội bộ."
            ),
            reason=reason,
            confidence=confidence,
            outcome=Outcome.OFF_TOPIC,
        )

    # Dynamic tool: if the route name matches a tool discovered from mcp-service
    # and it is not a shortcut/response decision, accept it as a generic tool call.
    if (
        discovered_tools
        and route_name in discovered_tools
        and route_name not in _NON_TOOL_DECISIONS
    ):
        return RouteDecision(
            decision=route_name,
            tool_arguments=decision.tool_arguments,
            reason=reason,
            confidence=confidence,
            outcome=Outcome.SUCCESS,
        )

    return RouteDecision(
        decision="rag_search",
        tool_arguments={"query": default_query},
        reason="unknown route fallback",
        confidence=0.0,
        outcome=Outcome.REFUSE,
    )


def _from_legacy_tool_decision(
    decision: ToolDecision,
    *,
    default_query: str,
    discovered_tools: set[str] | None = None,
) -> RouteDecision:
    if decision.tool_name == "hr_query":
        intent = str(decision.arguments.get("intent", "")).strip()
        if intent in VALID_HR_INTENTS:
            return RouteDecision(
                decision="hr_query",
                tool_arguments={"intent": intent},
                reason=decision.reason,
                confidence=0.0,
                outcome=Outcome.SUCCESS,
            )
    if decision.tool_name == "rag_search":
        query = str(decision.arguments.get("query") or default_query).strip() or default_query
        return RouteDecision(
            decision="rag_search",
            tool_arguments={"query": query},
            reason=decision.reason,
            confidence=0.0,
        )
    # Dynamic tool: accept if it was discovered from mcp-service.
    if discovered_tools and decision.tool_name in discovered_tools:
        return RouteDecision(
            decision=decision.tool_name,
            tool_arguments=decision.arguments,
            reason=decision.reason,
            confidence=0.0,
            outcome=Outcome.SUCCESS,
        )
    return RouteDecision(
        decision="rag_search",
        tool_arguments={"query": default_query},
        reason="legacy tool fallback",
        confidence=0.0,
    )
