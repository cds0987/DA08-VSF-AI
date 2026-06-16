"""resolve_date tool — quy đổi DETERMINISTIC ngày tương đối -> YYYY-MM-DD.

Model giỏi HIỂU ngôn ngữ ("thứ 4 tuần này", "mai") nhưng dở SỐ HỌC lịch (hay
đoán sai ngày -> tạo đơn nhầm ngày). Tool này tách vai: model TRÍCH XUẤT ngữ
nghĩa (kind/weekday/week_offset), server TÍNH ngày theo HÔM NAY (giờ VN).

Pure-compute: KHÔNG gọi service ngoài, KHÔNG cần config/secret. Built-in nên mặc
định BẬT (config node chỉ để ops tắt qua env nếu cần).
"""
from __future__ import annotations

import datetime as _dt
import logging
from collections.abc import Mapping
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from app.tools.base import register_tool

logger = logging.getLogger("mcp-service")

# Nhân viên VN nói ngày theo giờ Việt Nam, KHÔNG phải UTC -> resolve sai TZ lệch
# 1 ngày quanh nửa đêm.
_BUSINESS_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_WEEKDAY_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

DateKind = Literal[
    "today", "tomorrow", "day_after_tomorrow", "weekday", "offset_days", "absolute"
]


def _today() -> _dt.date:
    return _dt.datetime.now(_BUSINESS_TZ).date()


def compute(
    kind: str,
    *,
    weekday: Optional[int] = None,
    week_offset: int = 0,
    days: Optional[int] = None,
    date: Optional[str] = None,
    today: Optional[_dt.date] = None,
) -> dict[str, Any]:
    """Tính ngày từ ngữ nghĩa đã trích xuất. Tách riêng để test thuần (truyền today)."""
    today = today or _today()
    if kind == "today":
        d = today
    elif kind == "tomorrow":
        d = today + _dt.timedelta(days=1)
    elif kind == "day_after_tomorrow":
        d = today + _dt.timedelta(days=2)
    elif kind == "offset_days":
        d = today + _dt.timedelta(days=int(days or 0))
    elif kind == "weekday":
        if not weekday or not (1 <= int(weekday) <= 7):
            return {"error": "weekday phải 1..7 (1=Thứ Hai .. 7=Chủ Nhật) khi kind=weekday"}
        monday = today - _dt.timedelta(days=today.weekday())  # Thứ Hai của tuần hiện tại
        d = monday + _dt.timedelta(days=int(weekday) - 1, weeks=int(week_offset or 0))
    elif kind == "absolute":
        s = (date or "").strip()
        try:
            d = _dt.date.fromisoformat(s)
        except ValueError:
            return {"error": f"date không hợp lệ (cần YYYY-MM-DD): {s!r}"}
    else:
        return {"error": f"kind không hợp lệ: {kind!r}"}
    return {
        "date": d.isoformat(),
        "weekday_vi": _WEEKDAY_VI[d.weekday()],
        "today": today.isoformat(),
    }


class ResolveDateTool:
    name = "resolve_date"

    def __init__(self, settings: Any, params: Mapping[str, Any]) -> None:
        # Pure-compute: không giữ state/config nào.
        pass

    def register(self, mcp: Any) -> None:
        @mcp.tool()
        async def resolve_date(
            kind: DateKind,
            weekday: Optional[int] = None,
            week_offset: int = 0,
            days: Optional[int] = None,
            date: str = "",
            user_id: str = "",  # query-service tiêm — không dùng, chỉ để absorb.
        ) -> dict[str, Any]:
            """Quy đổi ngày TƯƠNG ĐỐI trong câu của user thành ngày dương lịch chính xác
            (YYYY-MM-DD) theo HÔM NAY (giờ Việt Nam). LUÔN gọi tool này cho mọi ngày
            tương đối thay vì tự suy tính.

            kind:
              - "today" / "tomorrow" / "day_after_tomorrow": hôm nay / mai / ngày kia.
              - "weekday": một thứ cụ thể. weekday=1..7 (1=Thứ Hai .. 7=Chủ Nhật);
                week_offset: 0=tuần này, 1=tuần sau, -1=tuần trước.
              - "offset_days": days = số ngày kể từ hôm nay (vd 3 = 3 ngày nữa).
              - "absolute": date = ngày user nói rõ ràng (YYYY-MM-DD).

            Trả về {date, weekday_vi, today}; nếu sai tham số -> {error}.
            """
            result = compute(
                kind, weekday=weekday, week_offset=week_offset, days=days, date=date
            )
            logger.info(
                "resolve_date kind=%s weekday=%s week_offset=%s -> %s",
                kind, weekday, week_offset, result.get("date") or result.get("error"),
            )
            return result

    async def verify(self) -> None:
        # Pure-compute: không có dependency để probe.
        return

    async def aclose(self) -> None:
        return


register_tool("resolve_date", lambda settings, params: ResolveDateTool(settings, params))
