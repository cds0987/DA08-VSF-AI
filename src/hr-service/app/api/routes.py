from __future__ import annotations

import hashlib
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import require_internal_token
from app.core.config import HrSettings, get_settings as load_hr_settings
from app.domain.repositories.hr_repository import HrRepository

logger = logging.getLogger("hr-service")

# Intent độ nhạy Cao: mỗi lần truy cập phải ghi audit (self-access — chỉ data của
# chính user, lọc cứng theo user_id từ token). KHÔNG log payload/số liệu.
SENSITIVE_INTENTS = {"payroll", "benefits", "performance"}

router = APIRouter(dependencies=[Depends(require_internal_token)])


def _mask_user_id(user_id: str) -> str:
    value = user_id.strip()
    if not value:
        return "unknown"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _audit(intent: str, user_id: str, found: bool) -> None:
    if intent in SENSITIVE_INTENTS:
        logger.info(
            "hr_audit intent=%s user=%s result=%s",
            intent,
            _mask_user_id(user_id),
            "found" if found else "not_found",
        )


def get_settings() -> HrSettings:
    return load_hr_settings()


async def _maybe_mock(
    repo: HrRepository, settings: HrSettings, intent: str, user_id: str
) -> None:
    """Stage develop: user đồng bộ chưa có hồ sơ -> tự sinh mock (idempotent) rồi để
    caller đọc lại. Production: no-op -> giữ 404/NO_INFO."""
    if settings.is_develop:
        await repo.provision_mock(intent, user_id)


def get_repo(settings: HrSettings = Depends(get_settings)) -> HrRepository:
    from app.infrastructure.db.postgres_hr_repository import PostgresHrRepository

    return PostgresHrRepository(settings.database_url)


class HrQueryRequest(BaseModel):
    user_id: str
    intent: Literal[
        "leave_balance",
        "leave_requests",
        "attendance",
        "onboarding",
        "payroll",
        "benefits",
        "performance",
    ]


class HrProfileRequest(BaseModel):
    user_id: str


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


def _payroll_summary(period: str, gross: float, deductions: float, net: float) -> str:
    return (
        f"Kỳ lương {period}: lương gross {gross:,.0f}, "
        f"khấu trừ {deductions:,.0f}, thực nhận {net:,.0f}."
    )


def _benefits_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return "Bạn chưa có phúc lợi nào được ghi nhận."
    names = ", ".join(str(item.get("name", "")) for item in items)
    return f"Bạn có các phúc lợi: {names}."


def _performance_summary(period: str, rating: str) -> str:
    return f"Đánh giá hiệu suất kỳ {period}: xếp loại {rating}."


@router.post("/hr/query")
async def hr_query(
    body: HrQueryRequest,
    repo: HrRepository = Depends(get_repo),
    settings: HrSettings = Depends(get_settings),
) -> dict[str, Any]:
    if body.intent == "leave_balance":
        dto = await repo.get_leave_balance(body.user_id)
        if dto is None and settings.auto_provision_leave_balance:
            # Lưới an toàn: user chưa được đồng bộ (vd admin tạo trước khi có event
            # user.created) -> tự tạo hồ sơ phép mặc định idempotent rồi đọc lại.
            await repo.ensure_leave_balance(
                body.user_id, settings.default_annual_leave, settings.default_sick_leave
            )
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
        if not dtos:
            await _maybe_mock(repo, settings, body.intent, body.user_id)
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
            await _maybe_mock(repo, settings, body.intent, body.user_id)
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

    if body.intent == "onboarding":
        dto = await repo.get_onboarding(body.user_id)
        if dto is None:
            await _maybe_mock(repo, settings, body.intent, body.user_id)
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

    if body.intent == "payroll":
        dtos = await repo.get_payroll(body.user_id)
        if not dtos:
            await _maybe_mock(repo, settings, body.intent, body.user_id)
            dtos = await repo.get_payroll(body.user_id)
        _audit(body.intent, body.user_id, bool(dtos))
        if not dtos:
            raise HTTPException(status_code=404, detail="no HR data for this user")
        latest = dtos[0]
        data = {
            "payroll": [
                {
                    "period": item.period,
                    "gross_salary": item.gross_salary,
                    "deductions": item.deductions,
                    "net_salary": item.net_salary,
                }
                for item in dtos
            ]
        }
        return {
            "intent": body.intent,
            "data": data,
            "summary": _payroll_summary(
                latest.period, latest.gross_salary, latest.deductions, latest.net_salary
            ),
        }

    if body.intent == "benefits":
        dto = await repo.get_benefits(body.user_id)
        if dto is None:
            await _maybe_mock(repo, settings, body.intent, body.user_id)
            dto = await repo.get_benefits(body.user_id)
        _audit(body.intent, body.user_id, dto is not None)
        if dto is None:
            raise HTTPException(status_code=404, detail="no HR data for this user")
        items = [{"name": item.name, "value": item.value} for item in dto.items]
        return {
            "intent": body.intent,
            "data": {"items": items},
            "summary": _benefits_summary(items),
        }

    dto = await repo.get_performance(body.user_id)
    if dto is None:
        await _maybe_mock(repo, settings, body.intent, body.user_id)
        dto = await repo.get_performance(body.user_id)
    _audit(body.intent, body.user_id, dto is not None)
    if dto is None:
        raise HTTPException(status_code=404, detail="no HR data for this user")
    data = {
        "period": dto.period,
        "rating": dto.rating,
        "kpi": dto.kpi,
        "reviewer_user_id": dto.reviewer_user_id,
    }
    return {
        "intent": body.intent,
        "data": data,
        "summary": _performance_summary(dto.period, dto.rating),
    }


@router.post("/hr/profile")
async def hr_profile(
    body: HrProfileRequest,
    repo: HrRepository = Depends(get_repo),
    settings: HrSettings = Depends(get_settings),
) -> dict[str, Any]:
    """Trả TOÀN BỘ hồ sơ HR của user trong 1 lần gọi (gộp 7 section) để LLM tự nhặt
    phần liên quan — thay vì bắt LLM chọn `intent` rời rạc (model hay bỏ trống/sai).
    Tự cấp leave_balance + dev-mock các section khi develop (như /hr/query). Self-access:
    user_id đến từ token (mcp tiêm), audit 1 lần dạng 'profile'."""
    uid = body.user_id

    # leave_balance: auto-provision như intent leave_balance.
    lb = await repo.get_leave_balance(uid)
    if lb is None and settings.auto_provision_leave_balance:
        await repo.ensure_leave_balance(uid, settings.default_annual_leave, settings.default_sick_leave)
        lb = await repo.get_leave_balance(uid)

    async def _get(intent: str, getter):
        dto = await getter(uid)
        empty = dto is None or (isinstance(dto, list) and not dto)
        if empty and settings.is_develop:
            await repo.provision_mock(intent, uid)
            dto = await getter(uid)
        return dto

    lrs = await _get("leave_requests", repo.get_leave_requests)
    att = await _get("attendance", repo.get_attendance)
    onb = await _get("onboarding", repo.get_onboarding)
    pay = await _get("payroll", repo.get_payroll)
    ben = await _get("benefits", repo.get_benefits)
    perf = await _get("performance", repo.get_performance)

    data: dict[str, Any] = {
        "leave_balance": None if lb is None else {
            "annual_total": lb.annual_total, "annual_used": lb.annual_used,
            "annual_remaining": lb.annual_remaining, "sick_total": lb.sick_total,
            "sick_used": lb.sick_used, "sick_remaining": lb.sick_remaining,
        },
        "leave_requests": [
            {"leave_type": r.leave_type, "start_date": r.start_date, "end_date": r.end_date,
             "days_count": r.days_count, "status": r.status}
            for r in (lrs or [])
        ],
        "attendance": None if att is None else {
            "period": att.period, "work_days": att.work_days,
            "late_count": att.late_count, "absent_count": att.absent_count,
        },
        "onboarding": None if onb is None else {
            "status": onb.status,
            "checklist": [{"task": i.task, "done": i.done} for i in onb.checklist],
            "completed_count": onb.completed_count, "total_count": onb.total_count,
        },
        "payroll": [
            {"period": p.period, "gross_salary": p.gross_salary,
             "deductions": p.deductions, "net_salary": p.net_salary}
            for p in (pay or [])
        ],
        "benefits": None if ben is None else {
            "items": [{"name": i.name, "value": i.value} for i in ben.items]
        },
        "performance": None if perf is None else {
            "period": perf.period, "rating": perf.rating,
            "kpi": perf.kpi, "reviewer_user_id": perf.reviewer_user_id,
        },
    }
    # Audit 1 lần (profile chạm cả intent nhạy cảm payroll/benefits/performance — self-access).
    logger.info("hr_audit intent=profile user=%s result=%s", _mask_user_id(uid),
                "found" if any(v for v in data.values()) else "empty")
    return {"intent": "profile", "data": data,
            "summary": "Hồ sơ HR cá nhân (phép, đơn nghỉ, chấm công, onboarding, lương, phúc lợi, hiệu suất)."}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
