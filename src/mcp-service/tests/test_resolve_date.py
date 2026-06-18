"""Khóa hành vi resolve_date.compute — quy đổi DETERMINISTIC theo today cố định.

today = Thứ Ba 2026-06-16 (mốc giống bug thực tế: user xin "thứ 4 tuần này").
"""
import datetime

from app.tools.resolve_date import compute

TODAY = datetime.date(2026, 6, 16)  # Thứ Ba


def test_weekday_this_week():
    # Token tiếng Việt: thu_4 = Thứ Tư = Wednesday (KHÔNG lệch sang Thursday).
    assert compute("weekday", weekday="thu_4", today=TODAY)["date"] == "2026-06-17"  # Thứ Tư
    assert compute("weekday", weekday="thu_6", today=TODAY)["date"] == "2026-06-19"  # Thứ Sáu
    assert compute("weekday", weekday="chu_nhat", today=TODAY)["date"] == "2026-06-21"  # CN


def test_weekday_next_and_prev_week():
    assert compute("weekday", weekday="thu_4", week_offset=1, today=TODAY)["date"] == "2026-06-24"
    # tuần trước là ngày đã qua -> past-date guard trả error
    result = compute("weekday", weekday="thu_4", week_offset=-1, today=TODAY)
    assert "error" in result and result.get("past_date") is True


def test_today_tomorrow_day_after():
    assert compute("today", today=TODAY)["date"] == "2026-06-16"
    assert compute("tomorrow", today=TODAY)["date"] == "2026-06-17"
    assert compute("day_after_tomorrow", today=TODAY)["date"] == "2026-06-18"


def test_offset_days_and_absolute():
    assert compute("offset_days", days=3, today=TODAY)["date"] == "2026-06-19"
    assert compute("absolute", date="2026-07-01", today=TODAY)["date"] == "2026-07-01"


def test_weekday_vi_and_today_echo():
    out = compute("weekday", weekday="thu_4", today=TODAY)
    assert out["weekday_vi"] == "Thứ Tư"
    assert out["today"] == "2026-06-16"


def test_span_days_returns_start_end_pair():
    # "nghỉ 5 ngày từ thứ 2 tuần sau" -> thu_2/week_offset=1 = 2026-06-22, +4 = 06-26.
    out = compute("weekday", weekday="thu_2", week_offset=1, span_days=5, today=TODAY)
    assert out["start_date"] == "2026-06-22"
    assert out["end_date"] == "2026-06-26"      # 5 ngày liên tiếp, KHÔNG phải +5
    assert out["end_weekday_vi"] == "Thứ Sáu"
    assert out["date"] == "2026-06-22"          # vẫn echo điểm gốc


def test_span_days_one_or_none_omits_range():
    # span<=1 hoặc không truyền -> không thêm start/end (đơn 1 ngày).
    assert "end_date" not in compute("tomorrow", today=TODAY)
    assert "end_date" not in compute("tomorrow", span_days=1, today=TODAY)


def test_span_days_with_offset_days():
    # "nghỉ 3 ngày kể từ mai" có thể trích offset_days=1, span_days=3.
    out = compute("offset_days", days=1, span_days=3, today=TODAY)
    assert out["start_date"] == "2026-06-17" and out["end_date"] == "2026-06-19"


def test_invalid_inputs_return_error():
    assert "error" in compute("weekday", today=TODAY)              # thiếu weekday
    assert "error" in compute("weekday", weekday="thu_9", today=TODAY)  # token lạ
    assert "error" in compute("absolute", date="not-a-date", today=TODAY)
    assert "error" in compute("xyz", today=TODAY)                 # kind lạ


def test_absolute_multiple_formats():
    # DD/MM/YYYY và DD-MM-YYYY được parse đúng
    assert compute("absolute", date="30/4/2027", today=TODAY)["date"] == "2027-04-30"
    assert compute("absolute", date="30-04-2027", today=TODAY)["date"] == "2027-04-30"
    assert compute("absolute", date="30.4.2027", today=TODAY)["date"] == "2027-04-30"
    assert compute("absolute", date="3/4/2027", today=TODAY)["date"] == "2027-04-03"


def test_absolute_missing_year_returns_error():
    # DD/MM không có năm -> error hỏi năm
    result = compute("absolute", date="30/4", today=TODAY)
    assert "error" in result
    assert "năm nào" in result["error"]
    assert "past_date" not in result  # không phải past_date, chỉ thiếu năm


def test_absolute_past_date_returns_error():
    # Ngày đã qua -> past-date guard
    result = compute("absolute", date="30/4/2026", today=TODAY)
    assert "error" in result
    assert result.get("past_date") is True
    assert "đã qua" in result["error"]
    # Gợi ý năm sau
    assert "30/04/2027" in result["error"]


def test_absolute_past_date_iso_returns_error():
    # YYYY-MM-DD đã qua cũng bị chặn
    result = compute("absolute", date="2026-01-15", today=TODAY)
    assert "error" in result and result.get("past_date") is True


def test_today_is_not_blocked():
    # Hôm nay không bị chặn (d < today là False khi d == today)
    assert compute("today", today=TODAY)["date"] == "2026-06-16"
