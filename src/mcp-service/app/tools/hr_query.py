"""HR query tool for personal self-service data.

The tool keeps the current user boundary inside the service and only exposes
the current user's own HR records. The mock data here is intentionally small so
we can wire the server-side MCP tool without pulling in a database layer yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import McpSettings
from app.tools.base import register_tool

HR_USER_ID = "11111111-1111-4111-8111-111111111111"
HR_FINANCE_USER_ID = "22222222-2222-4222-8222-222222222222"

HrIntent = Literal["leave_balance", "leave_requests", "attendance", "onboarding"]


@dataclass(frozen=True)
class HrRecord:
    leave_balance: dict[str, int]
    leave_requests: list[dict[str, Any]]
    attendance: dict[str, int]
    onboarding: dict[str, Any]


MOCK_HR_DATA: dict[str, HrRecord] = {
    HR_USER_ID: HrRecord(
        leave_balance={
            "annual_remaining": 8,
            "sick_remaining": 9,
        },
        leave_requests=[
            {
                "id": "leave-hr-001",
                "type": "annual",
                "from_date": "2026-06-10",
                "to_date": "2026-06-11",
                "status": "approved",
            },
            {
                "id": "leave-hr-002",
                "type": "sick",
                "from_date": "2026-06-18",
                "to_date": "2026-06-18",
                "status": "pending",
            },
        ],
        attendance={
            "work_days": 20,
            "late_count": 1,
            "absent_count": 0,
        },
        onboarding={
            "status": "completed",
            "checklist": [
                {"task": "Collect laptop and badge", "done": True},
                {"task": "Finish security training", "done": True},
                {"task": "Meet the team", "done": True},
            ],
        },
    ),
    HR_FINANCE_USER_ID: HrRecord(
        leave_balance={
            "annual_remaining": 5,
            "sick_remaining": 10,
        },
        leave_requests=[
            {
                "id": "leave-fin-001",
                "type": "annual",
                "from_date": "2026-06-18",
                "to_date": "2026-06-18",
                "status": "pending",
            }
        ],
        attendance={
            "work_days": 19,
            "late_count": 2,
            "absent_count": 1,
        },
        onboarding={
            "status": "in_progress",
            "checklist": [
                {"task": "Collect laptop and badge", "done": True},
                {"task": "Finish security training", "done": False},
                {"task": "Meet the team", "done": False},
            ],
        },
    ),
}

_ALLOWED_INTENTS: tuple[HrIntent, ...] = (
    "leave_balance",
    "leave_requests",
    "attendance",
    "onboarding",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _get_record(user_id: str) -> HrRecord:
    record = MOCK_HR_DATA.get(user_id)
    if record is None:
        raise ValueError("hr_query: no HR data available for the current user")
    return record


def _leave_balance_summary(data: dict[str, int]) -> str:
    return (
        f"Ban con {data['annual_remaining']} ngay phep nam va "
        f"{data['sick_remaining']} ngay phep om."
    )


def _leave_requests_summary(requests: list[dict[str, Any]]) -> str:
    if not requests:
        return "Ban chua co don nghi phep nao."
    latest = requests[0]
    return (
        f"Don nghi gan nhat la {latest['type']} tu {latest['from_date']} "
        f"den {latest['to_date']}, trang thai {latest['status']}."
    )


def _attendance_summary(data: dict[str, int]) -> str:
    return (
        f"Ban co {data['work_days']} ngay cong, di muon {data['late_count']} lan "
        f"va vang {data['absent_count']} ngay."
    )


def _onboarding_summary(data: dict[str, Any]) -> str:
    checklist = data.get("checklist") or []
    completed = sum(1 for item in checklist if isinstance(item, dict) and item.get("done"))
    total = len(checklist)
    return f"Trang thai onboarding la {data.get('status', '')}, da hoan tat {completed}/{total} muc."


def _result(intent: HrIntent, data: dict[str, Any], summary: str, alias_key: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "intent": intent,
        "data": data,
        "summary": summary,
    }
    payload[alias_key] = data
    return payload


class HrQueryTool:
    name = "hr_query"

    def __init__(self, settings: McpSettings, params: Mapping[str, Any]) -> None:
        self._settings = settings
        self._params = dict(params or {})
        nested_params = _mapping(self._params.get("params"))
        self._database_url = str(nested_params.get("database_url") or "").strip()

    def register(self, mcp: Any) -> None:
        @mcp.tool()
        async def hr_query(
            user_id: str,
            intent: Literal[
                "leave_balance",
                "leave_requests",
                "attendance",
                "onboarding",
            ],
        ) -> dict[str, Any]:
            """Read the current user's own HR data.

            user_id is injected by the caller and must never be guessed by the
            model.
            """

            if intent not in _ALLOWED_INTENTS:
                raise ValueError(
                    "hr_query: unsupported intent. "
                    "Allowed: leave_balance, leave_requests, attendance, onboarding"
                )

            record = _get_record(user_id)

            if intent == "leave_balance":
                data = dict(record.leave_balance)
                return _result(intent, data, _leave_balance_summary(data), "leave_balance")

            if intent == "leave_requests":
                data = {"requests": [dict(item) for item in record.leave_requests]}
                return _result(intent, data, _leave_requests_summary(data["requests"]), "leave_requests")

            if intent == "attendance":
                data = dict(record.attendance)
                return _result(intent, data, _attendance_summary(data), "attendance")

            data = dict(record.onboarding)
            return _result(intent, data, _onboarding_summary(data), "onboarding")

    async def verify(self) -> None:
        # Mock-backed tool: nothing to initialize or verify yet.
        return None

    async def aclose(self) -> None:
        # No resources to close in the mock-backed implementation.
        return None


register_tool("hr_query", lambda settings, params: HrQueryTool(settings, params))
