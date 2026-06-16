from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncGenerator
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.auth import require_internal_token
from app.core.config import HrSettings, get_settings as load_hr_settings
from app.domain.leave_policy import get_policy, registry_payload
from app.domain.repositories.hr_repository import HrRepository
from app.domain.repositories.leave_write_repository import (
    ApproverNotConfigured,
    InsufficientLeaveBalance,
    LeaveRequestConflict,
    LeaveRequestDuplicate,
    LeaveRequestForbidden,
    LeaveRequestNotFound,
    LeaveRequestOverlapWarning,
    LeaveWriteRepository,
)

logger = logging.getLogger("hr-service")

# Intent độ nhạy Cao: mỗi lần truy cập phải ghi audit (self-access — chỉ data của
# chính user, lọc cứng theo user_id từ token). KHÔNG log payload/số liệu.
SENSITIVE_INTENTS = {"payroll", "benefits", "performance"}

router = APIRouter(dependencies=[Depends(require_internal_token)])

# Endpoints không yêu cầu internal token (department names không nhạy cảm, cần thiết
# cho admin frontend chọn ACL khi upload document).
public_router = APIRouter()


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


async def get_repo(
    settings: HrSettings = Depends(get_settings),
) -> AsyncGenerator[HrRepository, None]:
    from app.infrastructure.db.postgres_hr_repository import PostgresHrRepository

    repo = PostgresHrRepository(settings.database_url)
    try:
        yield repo
    finally:
        await repo.aclose()


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


# ──────────────────────────── LEAVE WRITE ────────────────────────────
# leave_type validate ĐỘNG theo Leave Type Registry (4 rổ) thay vì Literal cứng —
# nguồn sự thật ở app/domain/leave_policy.py. Giá trị lạ -> 422 (xem _validate_leave_type).
LeaveType = str


async def get_write_repo(
    settings: HrSettings = Depends(get_settings),
) -> AsyncGenerator[LeaveWriteRepository, None]:
    """Dependency RIÊNG cho write (KHÔNG dùng get_repo) — test read override get_repo
    với FakeHrRepository (không có method write); test write override get_write_repo
    với fake write riêng. Tách dependency = tách interface (Bẫy 1)."""
    from app.infrastructure.db.postgres_hr_repository import PostgresHrRepository

    repo = PostgresHrRepository(settings.database_url)
    try:
        yield repo
    finally:
        await repo.aclose()


def get_publisher(request: Request) -> Any:
    """NATS publisher lưu ở app.state (lifespan set). None khi chưa khởi tạo (vd
    TestClient không chạy lifespan) -> publish bị bỏ qua (best-effort)."""
    return getattr(request.app.state, "publisher", None)


class LeaveCreateRequest(BaseModel):
    user_id: str
    leave_type: LeaveType
    start_date: str
    end_date: str
    reason: str = ""
    idempotency_key: Optional[str] = None
    # User đã xem cảnh báo chồng ngày và vẫn muốn tạo -> bỏ qua LeaveRequestOverlapWarning.
    confirm_overlap: bool = False


class LeaveUpdateRequest(BaseModel):
    user_id: str
    leave_type: LeaveType
    start_date: str
    end_date: str
    reason: str = ""
    idempotency_key: Optional[str] = None


class LeaveCancelRequest(BaseModel):
    user_id: str


class ApprovalActionRequest(BaseModel):
    approver_user_id: str
    reason: str = ""


def _map_leave_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ApproverNotConfigured):
        return HTTPException(status_code=422, detail="approver chưa được cấu hình")
    if isinstance(exc, LeaveRequestNotFound):
        return HTTPException(status_code=404, detail="leave request not found")
    if isinstance(exc, LeaveRequestForbidden):
        return HTTPException(status_code=403, detail="không có quyền với đơn này")
    if isinstance(exc, InsufficientLeaveBalance):
        return HTTPException(status_code=409, detail="không đủ hạn mức phép")
    if isinstance(exc, LeaveRequestDuplicate):
        # Trùng toàn bộ -> CHẶN (FE không cho "vẫn tạo"). detail object để FE nhận diện.
        return HTTPException(status_code=409, detail={
            "code": "leave_duplicate",
            "message": str(exc),
            "existing": [_existing_summary(exc.existing)] if exc.existing else [],
        })
    if isinstance(exc, LeaveRequestOverlapWarning):
        # Chồng ngày khác nội dung -> CẢNH BÁO (FE cho phép xác nhận tạo tiếp).
        return HTTPException(status_code=409, detail={
            "code": "leave_overlap",
            "message": str(exc),
            "existing": [_existing_summary(e) for e in exc.existing],
        })
    if isinstance(exc, LeaveRequestConflict):
        return HTTPException(status_code=409, detail="đơn không ở trạng thái hợp lệ")
    return HTTPException(status_code=500, detail="leave write error")


def _existing_summary(req: dict[str, Any]) -> dict[str, Any]:
    """Tóm tắt đơn đang đè (chỉ data của chính user) cho FE hiển thị cảnh báo."""
    return {
        "request_id": req.get("id"),
        "leave_type": req.get("leave_type"),
        "start_date": req.get("start_date"),
        "end_date": req.get("end_date"),
        "status": req.get("status"),
        "reason": req.get("reason"),
    }


def _validate_dates(start_date: str, end_date: str) -> None:
    import datetime as _dt

    try:
        start = _dt.date.fromisoformat(start_date)
        end = _dt.date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="start_date/end_date phải là YYYY-MM-DD")
    if start > end:
        raise HTTPException(status_code=422, detail="start_date phải <= end_date")


def _validate_leave_type(leave_type: str, start_date: str, end_date: str) -> None:
    """Loại nghỉ phải hợp lệ (theo registry) + tôn trọng định mức MỖI ĐƠN của rổ sự
    kiện (vd kết hôn ≤ 3 ngày, con kết hôn ≤ 1). Sai -> 422."""
    import datetime as _dt

    policy = get_policy(leave_type)
    if policy is None:
        valid = ", ".join(p["code"] for p in registry_payload())
        raise HTTPException(status_code=422, detail=f"leave_type không hợp lệ. Hợp lệ: {valid}")
    if policy.per_event_cap is not None:
        start = _dt.date.fromisoformat(start_date)
        end = _dt.date.fromisoformat(end_date)
        days = (end - start).days + 1
        if days > policy.per_event_cap:
            raise HTTPException(
                status_code=422,
                detail=f"{policy.label_vi} tối đa {policy.per_event_cap} ngày/lần (đơn này {days} ngày).",
            )


def _created_payload(req: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": req["id"],
        "requester_user_id": req["user_id"],
        "approver_user_id": req["approver_user_id"],
        "leave_type": req["leave_type"],
        "start_date": req["start_date"],
        "end_date": req["end_date"],
        "days_count": req["days_count"],
        "status": req["status"],
    }


def _status_payload(req: dict[str, Any], *, include_reason: bool = False) -> dict[str, Any]:
    payload = {
        "request_id": req["id"],
        "requester_user_id": req["user_id"],
        "approver_user_id": req["approver_user_id"],
        "status": req["status"],
    }
    if include_reason:
        payload["rejected_reason"] = req.get("rejected_reason")
    return payload


async def _publish_event(publisher: Any, subject: str, payload: dict[str, Any]) -> None:
    """Publish SAU commit, best-effort: NATS lỗi/None KHÔNG được làm sập write."""
    if publisher is None:
        return
    try:
        await publisher.publish(subject, payload)
    except Exception as exc:  # noqa: BLE001 — chủ ý nuốt mọi lỗi publish (best-effort)
        logger.warning("hr_event_publish_failed subject=%s error=%s", subject, exc)


@router.post("/hr/leave-requests", status_code=201)
async def create_leave_request(
    body: LeaveCreateRequest,
    repo: LeaveWriteRepository = Depends(get_write_repo),
    settings: HrSettings = Depends(get_settings),
    publisher: Any = Depends(get_publisher),
) -> dict[str, Any]:
    _validate_dates(body.start_date, body.end_date)
    _validate_leave_type(body.leave_type, body.start_date, body.end_date)
    try:
        result = await repo.create_leave_request(
            user_id=body.user_id,
            leave_type=body.leave_type,
            start_date=body.start_date,
            end_date=body.end_date,
            reason=body.reason,
            default_approver=settings.default_approver,
            idempotency_key=body.idempotency_key,
            confirm_overlap=body.confirm_overlap,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_leave_error(exc)
    req = result["request"]
    if result.get("created"):
        await _publish_event(publisher, "hr.leave_request.created", _created_payload(req))
    logger.info("hr_leave_create user=%s status=%s", _mask_user_id(body.user_id), req["status"])
    return req


@router.patch("/hr/leave-requests/{request_id}")
async def update_leave_request(
    request_id: str,
    body: LeaveUpdateRequest,
    repo: LeaveWriteRepository = Depends(get_write_repo),
    settings: HrSettings = Depends(get_settings),
    publisher: Any = Depends(get_publisher),
) -> dict[str, Any]:
    _validate_dates(body.start_date, body.end_date)
    _validate_leave_type(body.leave_type, body.start_date, body.end_date)
    try:
        result = await repo.update_leave_request(
            user_id=body.user_id,
            request_id=request_id,
            leave_type=body.leave_type,
            start_date=body.start_date,
            end_date=body.end_date,
            reason=body.reason,
            default_approver=settings.default_approver,
            idempotency_key=body.idempotency_key,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_leave_error(exc)
    req = result["request"]
    if result.get("mode") == "updated":
        await _publish_event(publisher, "hr.leave_request.updated", _created_payload(req))
    elif result.get("mode") == "replaced":
        old = result.get("replaced_request")
        if old:
            await _publish_event(publisher, "hr.leave_request.cancelled", _status_payload(old))
        await _publish_event(publisher, "hr.leave_request.created", _created_payload(req))
    logger.info("hr_leave_update user=%s mode=%s", _mask_user_id(body.user_id), result.get("mode"))
    return req


@router.post("/hr/leave-requests/{request_id}/cancel")
async def cancel_leave_request(
    request_id: str,
    body: LeaveCancelRequest,
    repo: LeaveWriteRepository = Depends(get_write_repo),
    publisher: Any = Depends(get_publisher),
) -> dict[str, Any]:
    try:
        result = await repo.cancel_leave_request(user_id=body.user_id, request_id=request_id)
    except Exception as exc:  # noqa: BLE001
        raise _map_leave_error(exc)
    req = result["request"]
    if result.get("changed"):
        await _publish_event(publisher, "hr.leave_request.cancelled", _status_payload(req))
    logger.info("hr_leave_cancel user=%s changed=%s", _mask_user_id(body.user_id), result.get("changed"))
    return req


@router.get("/hr/leave-requests/pending-approval")
async def pending_approval(
    approver_user_id: str,
    repo: LeaveWriteRepository = Depends(get_write_repo),
) -> dict[str, Any]:
    items = await repo.list_pending_approval(approver_user_id)
    return {"items": items, "count": len(items)}


async def _decide_leave(
    request_id: str,
    body: ApprovalActionRequest,
    action: str,
    repo: LeaveWriteRepository,
    publisher: Any,
) -> dict[str, Any]:
    try:
        result = await repo.update_leave_status(
            request_id=request_id,
            approver_user_id=body.approver_user_id,
            action=action,
            reason=body.reason,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_leave_error(exc)
    req = result["request"]
    if action == "approve":
        await _publish_event(publisher, "hr.leave_request.approved", _status_payload(req))
    else:
        await _publish_event(
            publisher, "hr.leave_request.rejected", _status_payload(req, include_reason=True)
        )
    return req


@router.post("/hr/leave-requests/{request_id}/approve")
async def approve_leave_request(
    request_id: str,
    body: ApprovalActionRequest,
    repo: LeaveWriteRepository = Depends(get_write_repo),
    publisher: Any = Depends(get_publisher),
) -> dict[str, Any]:
    return await _decide_leave(request_id, body, "approve", repo, publisher)


@router.post("/hr/leave-requests/{request_id}/reject")
async def reject_leave_request(
    request_id: str,
    body: ApprovalActionRequest,
    repo: LeaveWriteRepository = Depends(get_write_repo),
    publisher: Any = Depends(get_publisher),
) -> dict[str, Any]:
    return await _decide_leave(request_id, body, "reject", repo, publisher)


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


@public_router.get("/hr/leave-types")
async def list_leave_types() -> dict[str, Any]:
    """Taxonomy loại nghỉ (4 rổ luật LĐ VN) — nguồn sự thật cho FE + agent lấy động."""
    return {"leave_types": registry_payload()}


@public_router.get("/hr/departments")
async def list_departments(
    repo: HrRepository = Depends(get_repo),
) -> dict[str, list[str]]:
    departments = await repo.get_distinct_departments()
    return {"departments": departments}


@public_router.get("/hr/employees/departments")
async def list_employee_departments(
    repo: HrRepository = Depends(get_repo),
) -> dict[str, list[dict]]:
    """Trả danh sách {user_id, department} cho admin frontend (User Management page)."""
    items = await repo.get_employee_departments()
    return {"items": items}
