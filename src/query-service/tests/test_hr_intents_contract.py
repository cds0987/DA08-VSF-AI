"""Contract test: tập HR intent PHẢI khớp 3 tầng (query == mcp == hr) + nội bộ query.

Bug từng xảy ra: query-service hardcode 3 intent (leave_balance/leave_requests/payroll)
trong khi mcp + hr hỗ trợ 7 -> hỏi phúc lợi/đánh giá/chấm công ra "không lấy được".
Test này khoá để tái lệch là FAIL ngay ở unit, không cần deploy.

Đọc mcp-service & hr-service qua AST (KHÔNG import — chúng là service khác, không có
trên sys.path của query-service) nên chạy được trong CI unit(query-service).
"""
from __future__ import annotations

import ast
from pathlib import Path

from app.application.hr_intents import HR_INTENTS, HR_CLASSIFIER_INTENTS
from app.application.route_decision import VALID_HR_INTENTS as ROUTE_HR_INTENTS
from app.application.tool_decision import VALID_HR_INTENTS as TOOL_HR_INTENTS

_REPO = Path(__file__).resolve().parents[3]  # .../DA08-VSF


def _literal_values(file_path: Path, var_name: str) -> set[str]:
    """Trích các string trong assignment `var_name = Literal[...]` qua AST."""
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if var_name in targets and isinstance(node.value, ast.Subscript):
                return {
                    el.value
                    for el in ast.walk(node.value)
                    if isinstance(el, ast.Constant) and isinstance(el.value, str)
                }
    raise AssertionError(f"{var_name} (Literal) not found in {file_path}")


def _route_literal_values(file_path: Path) -> set[str]:
    """hr-service routes.py: intent Literal[...] nằm trong HrQueryRequest.intent."""
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "intent" and isinstance(node.annotation, ast.Subscript):
                return {
                    el.value
                    for el in ast.walk(node.annotation)
                    if isinstance(el, ast.Constant) and isinstance(el.value, str)
                }
    raise AssertionError(f"intent Literal not found in {file_path}")


def test_query_internal_constants_match():
    assert ROUTE_HR_INTENTS == HR_INTENTS
    assert TOOL_HR_INTENTS == HR_INTENTS
    assert HR_CLASSIFIER_INTENTS == {f"hr:{i}" for i in HR_INTENTS}


def test_matches_mcp_service():
    mcp_intents = _literal_values(
        _REPO / "src" / "mcp-service" / "app" / "tools" / "hr_query.py", "HrIntent"
    )
    assert mcp_intents == HR_INTENTS, f"query {HR_INTENTS} != mcp {mcp_intents}"


def test_matches_hr_service():
    hr_intents = _route_literal_values(
        _REPO / "src" / "hr-service" / "app" / "api" / "routes.py"
    )
    assert hr_intents == HR_INTENTS, f"query {HR_INTENTS} != hr-service {hr_intents}"


def test_all_seven_present():
    assert HR_INTENTS == {
        "leave_balance", "leave_requests", "attendance",
        "onboarding", "payroll", "benefits", "performance",
    }
