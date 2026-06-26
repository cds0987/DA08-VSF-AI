# -*- coding: utf-8 -*-
"""Soft-adapter verify_answer (//hóa reasoning-off): tách 'thinking-prefix' (BƯỚC 1/2, Phân tích &
Kiểm tra, Tổng hợp...) khỏi answer + glyph-normalize. Bug screenshot: model in '**BƯỚC 1 —...'
(markdown prefix) -> rò vào message. Test ĐẦY ĐỦ nhiều biến thể model tránh bỏ sót."""
import unicodedata

import pytest

from app.agents.roles._llm import _va_is_struct, _va_need_more, _va_split, _va_normalize

A = "Người lao động nghỉ 03 ngày nguyên lương [1]."  # answer chuẩn dùng chung

# ───── CASE CẦN TÁCH (struct=True, _va_split -> answer sạch) ─────
SPLIT_CASES = [
    # (label, content, expected_answer)
    ("buoc2 markdown",        f"**BƯỚC 1 — TỔNG HỢP & KIỂM TRA:** Đủ dữ liệu. BƯỚC 2 — XUẤT: {A}", A),
    ("buoc2 newline",         f"BƯỚC 1 — KIỂM TRA: Đủ.\n\nBƯỚC 2 — XUẤT:\n{A}", A),
    ("buoc2 md-header",       f"## BƯỚC 1 — KIỂM TRA\nĐủ.\n## BƯỚC 2 — XUẤT\n{A}", A),
    ("buoc2 mixed-case",      f"**Bước 1 — Kiểm tra:** Đủ. Bước 2 — Xuất: {A}", A),
    ("buoc2 hyphen",          f"BƯỚC 1 - KIỂM TRA: Đủ. BƯỚC 2 - XUẤT: {A}", A),
    ("buoc2 blockquote",      f"> BƯỚC 1 — KIỂM TRA: Đủ\n> BƯỚC 2 — XUẤT: {A}", A),
    ("buoc2 italic",          f"*BƯỚC 1 — TỔNG HỢP:* Đủ\nBƯỚC 2 — XUẤT: {A}", A),
    ("buoc2 extra-ws",        f"\n\n**BƯỚC 1 — KIỂM TRA:**\n\nĐủ.\n\nBƯỚC 2 — XUẤT:\n\n{A}", A),
    ("buoc1-only verdict.",   f"**BƯỚC 1 — KIỂM TRA:** Đủ. {A}", A),
    ("buoc1-only verdict-sent", f"BƯỚC 1 — TỔNG HỢP & KIỂM TRA: Đủ dữ liệu để trả lời.\n{A}", A),
    ("header phan-tich&kt",   f"**Phân tích & Kiểm tra:** {A}", A),
    ("header tong-hop",       f"Tổng hợp: {A}", A),
    ("header kiem-tra+verdict", f"**Kiểm tra:** Đủ. {A}", A),
    ("header phan-tich-va-kt", f"Phân tích và kiểm tra:\n{A}", A),
    ("header danh-gia",       f"**Đánh giá:** {A}", A),
    ("header nhan-dinh+verdict", f"Nhận định: Đủ thông tin. {A}", A),
    ("glyph fullwidth cite",  f"**Kiểm tra:** {A.replace('[1]', '【1】')}", A),
    # bare-verdict KHÔNG kèm BƯỚC (leak phát hiện qua Playwright)
    ("bare-verdict du-tra-loi", f"Dữ liệu đã đủ để trả lời phần cốt lõi của câu hỏi.\n\n{A}", A),
    ("bare-verdict noidung",   f"Nội dung thu thập đã đủ để trả lời phần cốt lõi về chính sách nghỉ. {A}", A),
    ("bare-verdict thongtin",  f"Thông tin đã đủ để trả lời câu hỏi. {A}", A),
    ("bare-verdict hien-co",   f"Dữ liệu hiện có đã đủ trả lời. {A}", A),
]

# ───── CASE GIỮ NGUYÊN (struct=False -> answer thường, KHÔNG strip) ─────
KEEP_CASES = [
    ("clean answer",          A),
    ("process buoc-thuong",   "Quy trình nghỉ việc: Bước 1: nộp đơn. Bước 2: chờ duyệt [1]."),
    ("numbered list",         "1. Nộp đơn\n2. Chờ duyệt\n3. Nhận kết quả [1]."),
    ("start-Du no-struct",    "Đủ điều kiện nghỉ phép là làm việc đủ 12 tháng [1]."),
    ("mention kiem-tra",      "Để kiểm tra số phép, bạn xem mục Nhân sự nhé [1]."),
    ("mention xuat",          "Bạn cần xuất trình giấy tờ y tế khi nghỉ ốm > 3 ngày [1]."),
    ("start phan-tich no-colon", "Phân tích chi phí cho thấy mức tăng 5% [1]."),
    ("start tong-hop no-colon", "Tổng hợp các khoản phụ cấp gồm: ăn trưa, đi lại [1]."),
    ("greeting",              "Chào bạn! Theo quy định, bạn được nghỉ 03 ngày [1]."),
    ("luu-y header (not think)", "**Lưu ý:** Bạn nên nộp đơn trước 3 ngày làm việc [1]."),
    ("fallback no-info",      "Mình chưa tìm được thông tin phù hợp. Bạn thử hỏi lại nhé."),
    # false-positive cho bare-verdict: answer có 'Dữ liệu/Thông tin' nhưng KHÔNG phải verdict 'đã đủ trả lời'
    ("data cho-thay",         "Dữ liệu hệ thống cho thấy bạn còn 12 ngày phép năm nay [1]."),
    ("thongtin chi-tiet",     "Thông tin chi tiết về phụ cấp gồm: ăn trưa, đi lại [1]."),
    ("noidung tai-lieu",      "Nội dung tài liệu nội bộ quy định nghỉ kết hôn 03 ngày [1]."),
]


def _real_flow(content: str) -> str:
    """Mô phỏng astream_verify_answer: chỉ split khi struct (else stream live nguyên answer).
    full = _va_normalize(content) trước khi split (glyph/NFC)."""
    full = _va_normalize(content)
    if _va_is_struct(full):
        return _va_split(full)[0]
    return content


@pytest.mark.parametrize("label,content,expected", SPLIT_CASES, ids=[c[0] for c in SPLIT_CASES])
def test_split_strips_thinking_prefix(label, content, expected):
    assert _va_is_struct(_va_normalize(content)), f"{label}: phải nhận diện struct"
    ans = _real_flow(content)
    assert "BƯỚC" not in ans.upper(), f"{label}: còn rò 'BƯỚC' -> {ans!r}"
    assert ans.strip() == expected.strip(), f"{label}: answer sai -> {ans!r}"


@pytest.mark.parametrize("label,content", KEEP_CASES, ids=[c[0] for c in KEEP_CASES])
def test_keep_normal_answer_no_false_positive(label, content):
    # guard thật = _va_is_struct False -> stream live, KHÔNG split -> answer nguyên vẹn
    assert not _va_is_struct(_va_normalize(content)), f"{label}: nhận nhầm struct (false-positive)"
    assert _real_flow(content).strip() == content.strip(), f"{label}: nội dung answer bị đổi"


def test_need_more_in_struct():
    nm, missing = _va_need_more("BƯỚC 1 — KIỂM TRA: Chưa đủ. BƯỚC 2 — XUẤT: <<NEED_MORE>> cần quy trình chi tiết")
    assert nm and "quy trình" in missing


def test_need_more_bare():
    nm, missing = _va_need_more("<<NEED_MORE>> cần tra thêm chính sách thưởng")
    assert nm and "thưởng" in missing


def test_nfd_unicode_buoc():
    # model trả diacritic DECOMPOSED (NFD) -> normalize NFC vẫn nhận + tách
    content = unicodedata.normalize("NFD", f"BƯỚC 1 — KIỂM TRA: Đủ. BƯỚC 2 — XUẤT: {A}")
    assert _va_is_struct(content)
    ans, _ = _va_split(_va_normalize(content))
    assert "BƯỚC" not in ans.upper() and "03 ngày" in ans


def test_glyph_normalize():
    assert _va_normalize("nghỉ 03 ngày 【1】〔2〕（3）") == "nghỉ 03 ngày [1][2](3)"
