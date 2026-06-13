"""Routing: cả 7 HR intent qua route_decision PHẢI ra hr_query (KHÔNG bị REFUSE).

Trước đây 4 intent (attendance/onboarding/benefits/performance) rơi vào nhánh
"invalid hr intent" -> REFUSE -> rag_search -> "không lấy được dữ liệu HR".
"""
from __future__ import annotations

import pytest

from app.application.hr_intents import HR_INTENTS
from app.application.route_decision import RouteDecision, normalize_route_decision
from app.domain.outcome import Outcome


@pytest.mark.parametrize("intent", sorted(HR_INTENTS))
def test_route_decision_accepts_all_hr_intents(intent: str):
    decision = RouteDecision(
        decision="hr_query",
        tool_arguments={"intent": intent},
        confidence=0.9,
    )
    out = normalize_route_decision(decision, default_query="câu hỏi gốc")
    assert out.decision == "hr_query", f"{intent} bị đẩy sang {out.decision}"
    assert out.tool_arguments == {"intent": intent}
    assert out.outcome == Outcome.SUCCESS


def test_route_decision_rejects_unknown_intent():
    out = normalize_route_decision(
        RouteDecision(decision="hr_query", tool_arguments={"intent": "salary_xyz"}),
        default_query="q",
    )
    # intent lạ -> KHÔNG hr_query (fallback rag_search/REFUSE) — đúng kỳ vọng.
    assert out.decision != "hr_query"
