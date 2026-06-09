"""HR query tool — đọc dữ liệu HR cá nhân từ mcp_db.hr_mock.

user_id do MCP client (query-service) inject từ JWT.
Tool không tin user_id do LLM điền — không có đường query data người khác.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Literal

from app.core.config import McpSettings
from app.domain.repositories.hr_repository import HrRepository
from app.tools.base import register_tool

logger = logging.getLogger("mcp-service")


def _build_hr_repository(database_url: str) -> HrRepository:
    from app.infrastructure.db.postgres_hr_repository import PostgresHrRepository
    return PostgresHrRepository(database_url)


# ── summary builders ──────────────────────────────────────────────────────────

def _leave_balance_summary(annual_remaining: int, sick_remaining: int) -> str:
    return (
        f"Bạn còn {annual_remaining} ngày phép năm "
        f"và {sick_remaining} ngày phép ốm."
    )


def _leave_requests_summary(requests: list[dict[str, Any]]) -> str:
    if not requests:
        return "Bạn chưa có đơn nghỉ phép nào."
    r = requests[0]
    return (
        f"Đơn nghỉ gần nhất là {r['leave_type']} "
        f"từ {r['start_date']} đến {r['end_date']}, "
        f"trạng thái {r['status']}."
    )


def _attendance_summary(work_days: int, late_count: int, absent_count: int) -> str:
    return (
        f"Tháng này bạn có {work_days} ngày công, "
        f"đi muộn {late_count} lần và vắng {absent_count} ngày."
    )


def _onboarding_summary(status: str, completed: int, total: int) -> str:
    return (
        f"Trạng thái onboarding: {status}, "
        f"đã hoàn thành {completed}/{total} mục."
    )


# ── tool ──────────────────────────────────────────────────────────────────────

class HrQueryTool:
    name = "hr_query"

    def __init__(self, settings: McpSettings, params: Mapping[str, Any]) -> None:
        nested = dict(params.get("params") or {})
        database_url = str(nested.get("database_url") or "").strip()
        self._repo: HrRepository = _build_hr_repository(database_url)

    def register(self, mcp: Any) -> None:
        repo = self._repo

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

            user_id is injected by the caller from JWT and must never be
            guessed by the model.
            """
            if intent == "leave_balance":
                dto = await repo.get_leave_balance(user_id)
                if dto is None:
                    raise ValueError("hr_query: no HR data for this user")
                data: dict[str, Any] = {
                    "annual_total": dto.annual_total,
                    "annual_used": dto.annual_used,
                    "annual_remaining": dto.annual_remaining,
                    "sick_total": dto.sick_total,
                    "sick_used": dto.sick_used,
                    "sick_remaining": dto.sick_remaining,
                }
                return {
                    "intent": intent,
                    "data": data,
                    "summary": _leave_balance_summary(
                        dto.annual_remaining, dto.sick_remaining
                    ),
                }

            if intent == "leave_requests":
                dtos = await repo.get_leave_requests(user_id)
                requests = [
                    {
                        "leave_type": r.leave_type,
                        "start_date": r.start_date,
                        "end_date": r.end_date,
                        "days_count": r.days_count,
                        "status": r.status,
                    }
                    for r in dtos
                ]
                return {
                    "intent": intent,
                    "data": {"requests": requests},
                    "summary": _leave_requests_summary(requests),
                }

            if intent == "attendance":
                dto = await repo.get_attendance(user_id)
                if dto is None:
                    raise ValueError("hr_query: no HR data for this user")
                data = {
                    "period": dto.period,
                    "work_days": dto.work_days,
                    "late_count": dto.late_count,
                    "absent_count": dto.absent_count,
                }
                return {
                    "intent": intent,
                    "data": data,
                    "summary": _attendance_summary(
                        dto.work_days, dto.late_count, dto.absent_count
                    ),
                }

            # onboarding
            dto = await repo.get_onboarding(user_id)
            if dto is None:
                raise ValueError("hr_query: no HR data for this user")
            data = {
                "status": dto.status,
                "checklist": [
                    {"task": item.task, "done": item.done}
                    for item in dto.checklist
                ],
                "completed_count": dto.completed_count,
                "total_count": dto.total_count,
            }
            return {
                "intent": intent,
                "data": data,
                "summary": _onboarding_summary(
                    dto.status, dto.completed_count, dto.total_count
                ),
            }

    async def verify(self) -> None:
        logger.info("mcp_tool_verify_start tool=%s", self.name)
        await self._repo.ping()
        logger.info("mcp_tool_verify_ok tool=%s", self.name)

    async def aclose(self) -> None:
        await self._repo.aclose()


register_tool("hr_query", lambda settings, params: HrQueryTool(settings, params))
