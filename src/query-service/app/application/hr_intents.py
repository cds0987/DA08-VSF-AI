"""Single source of truth cho tập HR intent của query-service.

PHẢI khớp mcp-service (src/mcp-service/app/tools/hr_query.py `HrIntent`) và
hr-service (POST /hr/query Literal). Lệch 1 tầng -> model không gọi được intent
thiếu (vd attendance/benefits/performance/onboarding -> 'không lấy được dữ liệu HR').
Mọi module trong query-service import từ ĐÂY, KHÔNG khai báo lại tập intent.
"""
from __future__ import annotations

from typing import Final, Literal, get_args

# Enum dùng cho tool schema (bind_tools) — model thấy đủ 7 giá trị.
HrIntentLiteral = Literal[
    "leave_balance",
    "leave_requests",
    "attendance",
    "onboarding",
    "payroll",
    "benefits",
    "performance",
]

# Tập intent hợp lệ (validate/gate ở route_decision, tool_decision, mcp tool-spec).
HR_INTENTS: Final[frozenset[str]] = frozenset(get_args(HrIntentLiteral))

# Taxonomy của intent_classifier dùng tiền tố "hr:" (vd "hr:payroll").
HR_CLASSIFIER_INTENTS: Final[frozenset[str]] = frozenset(f"hr:{i}" for i in HR_INTENTS)
