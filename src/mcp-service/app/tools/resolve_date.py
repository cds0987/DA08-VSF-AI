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
import re
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

# Token thứ TIẾNG VIỆT -> ISO weekday (Mon=0..Sun=6). Dùng token (không dùng số) để
# tránh lệch: tiếng Việt "thứ 4" = Wednesday, KHÁC ISO 4 (= Thursday). Model map
# thẳng "thứ 4" -> "thu_4", không phải làm số học.
ViWeekday = Literal["thu_2", "thu_3", "thu_4", "thu_5", "thu_6", "thu_7", "chu_nhat"]
_VI_WEEKDAY_TO_ISO: dict[str, int] = {
    "thu_2": 0,   # Thứ Hai  = Monday
    "thu_3": 1,   # Thứ Ba   = Tuesday
    "thu_4": 2,   # Thứ Tư   = Wednesday
    "thu_5": 3,   # Thứ Năm  = Thursday
    "thu_6": 4,   # Thứ Sáu  = Friday
    "thu_7": 5,   # Thứ Bảy  = Saturday
    "chu_nhat": 6,  # Chủ Nhật = Sunday
}

# Regex cho kind="absolute": nhận nhiều định dạng ngày người dùng hay gõ
_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")          # YYYY-MM-DD
_DMY_FULL_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$")  # DD/MM/YYYY
_DM_ONLY_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})$")          # DD/MM (thiếu năm)


def _today() -> _dt.date:
    return _dt.datetime.now(_BUSINESS_TZ).date()


def compute(
    kind: str,
    *,
    weekday: Optional[str] = None,
    week_offset: int = 0,
    days: Optional[int] = None,
    span_days: Optional[int] = None,
    date: Optional[str] = None,
    today: Optional[_dt.date] = None,
) -> dict[str, Any]:
    """Tính ngày từ ngữ nghĩa đã trích xuất. Tách riêng để test thuần (truyền today).

    span_days: số ngày nghỉ LIÊN TIẾP kể từ ngày tính được (vd "5 ngày từ thứ 2
    tuần sau" -> span_days=5). Khi có, trả thêm start_date/end_date = [d, d+span-1]
    để model KHỎI tự cộng ngày (model dở số học lịch). span_days<=1 -> bỏ qua.
    """
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
        iso = _VI_WEEKDAY_TO_ISO.get(str(weekday or "").strip().lower())
        if iso is None:
            return {"error": "weekday phải là thu_2..thu_7 hoặc chu_nhat khi kind=weekday"}
        monday = today - _dt.timedelta(days=today.weekday())  # Thứ Hai của tuần hiện tại
        d = monday + _dt.timedelta(days=iso, weeks=int(week_offset or 0))
    elif kind == "absolute":
        s = (date or "").strip()
        d = None
        m = _ISO_RE.match(s)
        if m:
            try:
                d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return {"error": f"Ngày không hợp lệ: {s!r}"}
        if d is None:
            m = _DMY_FULL_RE.match(s)
            if m:
                try:
                    d = _dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                except ValueError:
                    return {"error": f"Ngày không hợp lệ: {s!r}"}
        if d is None:
            m = _DM_ONLY_RE.match(s)
            if m:
                day_str, month_str = m.group(1), m.group(2)
                return {"error": (
                    f"Bạn muốn nghỉ ngày {day_str}/{month_str} năm nào? "
                    f"Nếu là năm tới thì sẽ là {day_str}/{month_str}/{today.year + 1}."
                )}
        if d is None:
            return {"error": f"Không nhận ra định dạng ngày: {s!r}. Vui lòng dùng DD/MM/YYYY."}
    else:
        return {"error": f"kind không hợp lệ: {kind!r}"}
    # Past-date guard — áp dụng cho mọi kind
    if d < today:
        try:
            suggested = _dt.date(d.year + 1, d.month, d.day)
            hint = f" Bạn có muốn đặt ngày {suggested.strftime('%d/%m/%Y')} không?"
        except ValueError:
            hint = ""
        return {
            "error": (
                f"Ngày {d.strftime('%d/%m/%Y')} đã qua "
                f"(hôm nay {today.strftime('%d/%m/%Y')}).{hint}"
            ),
            "past_date": True,
            "today": today.isoformat(),
        }
    out: dict[str, Any] = {
        "date": d.isoformat(),
        "weekday_vi": _WEEKDAY_VI[d.weekday()],
        "today": today.isoformat(),
    }
    if span_days is not None and int(span_days) > 1:
        end = d + _dt.timedelta(days=int(span_days) - 1)  # 5 ngày -> +4
        out["start_date"] = d.isoformat()
        out["end_date"] = end.isoformat()
        out["end_weekday_vi"] = _WEEKDAY_VI[end.weekday()]
    return out


class ResolveDateTool:
    name = "resolve_date"

    def __init__(self, settings: Any, params: Mapping[str, Any]) -> None:
        # Pure-compute: không giữ state/config nào.
        pass

    def register(self, mcp: Any) -> None:
        @mcp.tool()
        async def resolve_date(
            kind: DateKind,
            weekday: Optional[ViWeekday] = None,
            week_offset: int = 0,
            days: Optional[int] = None,
            span_days: Optional[int] = None,
            date: str = "",
            user_id: str = "",  # query-service tiêm — không dùng, chỉ để absorb.
        ) -> dict[str, Any]:
            """Quy đổi ngày TƯƠNG ĐỐI trong câu của user thành ngày dương lịch chính xác
            (YYYY-MM-DD) theo HÔM NAY (giờ Việt Nam). LUÔN gọi tool này cho mọi ngày
            tương đối thay vì tự suy tính.

            kind:
              - "today" / "tomorrow" / "day_after_tomorrow": hôm nay / mai / ngày kia.
              - "weekday": một thứ trong tuần. weekday dùng ĐÚNG token tiếng Việt:
                "thu_2"=Thứ Hai, "thu_3"=Thứ Ba, "thu_4"=Thứ Tư, "thu_5"=Thứ Năm,
                "thu_6"=Thứ Sáu, "thu_7"=Thứ Bảy, "chu_nhat"=Chủ Nhật (vd user nói
                "thứ 4" -> weekday="thu_4"). week_offset: 0=tuần này, 1=tuần sau, -1=trước.
              - "offset_days": days = số ngày kể từ hôm nay (vd 3 = 3 ngày nữa).
              - "absolute": date = ngày user nói rõ ràng (YYYY-MM-DD).

            span_days: số ngày nghỉ LIÊN TIẾP (vd "nghỉ 5 ngày từ thứ 2 tuần sau"
              -> kind=weekday, weekday=thu_2, week_offset=1, span_days=5). Khi có,
              kết quả trả thêm start_date + end_date (= ngày tính được + span-1) —
              dùng cặp này cho đơn nghỉ, KHÔNG tự cộng ngày.

            Trả về {date, weekday_vi, today} (+ {start_date,end_date,end_weekday_vi}
            khi span_days>1); nếu sai tham số -> {error}.
            """
            result = compute(
                kind, weekday=weekday, week_offset=week_offset, days=days,
                span_days=span_days, date=date,
            )
            logger.info(
                "resolve_date kind=%s weekday=%s week_offset=%s span_days=%s -> %s",
                kind, weekday, week_offset, span_days,
                result.get("end_date") or result.get("date") or result.get("error"),
            )
            return result

    async def verify(self) -> None:
        # Pure-compute: không có dependency để probe.
        return

    async def aclose(self) -> None:
        return


register_tool("resolve_date", lambda settings, params: ResolveDateTool(settings, params))
