from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import require_internal_token
from app.core.config import HrSettings, get_settings as load_hr_settings
from app.domain.repositories.hr_repository import HrRepository

router = APIRouter(dependencies=[Depends(require_internal_token)])


def get_settings() -> HrSettings:
    return load_hr_settings()


def get_repo(settings: HrSettings = Depends(get_settings)) -> HrRepository:
    from app.infrastructure.db.postgres_hr_repository import PostgresHrRepository

    return PostgresHrRepository(settings.database_url)


class HrQueryRequest(BaseModel):
    user_id: str
    intent: Literal["leave_balance", "leave_requests", "attendance", "onboarding"]


def _leave_balance_summary(annual_remaining: int, sick_remaining: int) -> str:
    return f"Bạn còn {annual_remaining} ngày phép năm và {sick_remaining} ngày phép ốm."


def _leave_requests_summary(requests: list[dict[str, Any]]) -> str:
    if not requests:
        return "Bạn chưa có đơn nghỉ phép nào."
    request = requests[0]
    return (
        f"Đơn nghỉ gần nhất là {request['leave_type']} từ {request['start_date']} "
        f"đến {request['end_date']}, trạng thái {request['status']}."
    )


def _attendance_summary(work_days: int, late_count: int, absent_count: int) -> str:
    return (
        f"Tháng này bạn có {work_days} ngày công, "
        f"đi muộn {late_count} lần và vắng {absent_count} ngày."
    )


def _onboarding_summary(status: str, completed: int, total: int) -> str:
    return f"Trạng thái onboarding: {status}, đã hoàn thành {completed}/{total} mục."


@router.post("/hr/query")
async def hr_query(
    body: HrQueryRequest,
    repo: HrRepository = Depends(get_repo),
) -> dict[str, Any]:
    if body.intent == "leave_balance":
        dto = await repo.get_leave_balance(body.user_id)
        if dto is None:
            raise HTTPException(status_code=404, detail="no HR data for this user")
        data = {
            "annual_total": dto.annual_total,
            "annual_used": dto.annual_used,
            "annual_remaining": dto.annual_remaining,
            "sick_total": dto.sick_total,
            "sick_used": dto.sick_used,
            "sick_remaining": dto.sick_remaining,
        }
        return {
            "intent": body.intent,
            "data": data,
            "summary": _leave_balance_summary(dto.annual_remaining, dto.sick_remaining),
        }

    if body.intent == "leave_requests":
        dtos = await repo.get_leave_requests(body.user_id)
        requests = [
            {
                "leave_type": item.leave_type,
                "start_date": item.start_date,
                "end_date": item.end_date,
                "days_count": item.days_count,
                "status": item.status,
            }
            for item in dtos
        ]
        return {
            "intent": body.intent,
            "data": {"requests": requests},
            "summary": _leave_requests_summary(requests),
        }

    if body.intent == "attendance":
        dto = await repo.get_attendance(body.user_id)
        if dto is None:
            raise HTTPException(status_code=404, detail="no HR data for this user")
        data = {
            "period": dto.period,
            "work_days": dto.work_days,
            "late_count": dto.late_count,
            "absent_count": dto.absent_count,
        }
        return {
            "intent": body.intent,
            "data": data,
            "summary": _attendance_summary(dto.work_days, dto.late_count, dto.absent_count),
        }

    dto = await repo.get_onboarding(body.user_id)
    if dto is None:
        raise HTTPException(status_code=404, detail="no HR data for this user")
    data = {
        "status": dto.status,
        "checklist": [{"task": item.task, "done": item.done} for item in dto.checklist],
        "completed_count": dto.completed_count,
        "total_count": dto.total_count,
    }
    return {
        "intent": body.intent,
        "data": data,
        "summary": _onboarding_summary(dto.status, dto.completed_count, dto.total_count),
    }


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
