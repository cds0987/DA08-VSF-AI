# claude-fix — Nhật ký FIX lỗi từ eval (claude-querytest.md)

> Mỗi fix: **Motivation → Solution → Implementation (code: làm gì / đổi gì / ở đâu) → Result
> (verify: CI/CD + Playwright đa-case + Langfuse)**. Tuân thủ kiến trúc có sẵn (MOSA + OOP +
> KHÔNG hardcode + mọi call qua AI Router). Mới nhất ở trên.

---

## FIX #1 — Vector-rasterize làm doc chart-heavy FAIL ingest (vượt MAX_OCR_PAGES) [2026-06-23]

**Motivation.** Eval Section I bắt: `2402.04355v3.pdf` fail ingest (0 chunk) — *"requires OCR on
43 images but exceeds MAX_OCR_PAGES (25)"*. Fix vector-rasterize (Section I) thêm 1 full-page raster
cho MỖI trang có chart-vẽ-vector → doc nhiều trang-chart đẩy tổng ảnh-OCR vượt trần 25 → cả doc
FAIL (mất sạch text-layer vốn parse tốt). Vector-raster chỉ là **bổ sung** (text-layer vẫn còn) nên
KHÔNG được phép làm doc fail.

**Solution.** Graceful degradation, KHÔNG đổi bất biến fail-closed cho ảnh THIẾT YẾU:
- Ảnh thiết yếu (trang scan không-text, ảnh raster nhúng) → giữ nguyên; nếu RIÊNG chúng vượt trần
  → vẫn raise (bất biến cũ).
- Vector-raster (bổ sung) → CHỈ thêm khi còn budget dưới `MAX_OCR_PAGES`. Hết budget → bỏ qua
  (doc vẫn ingest bằng text-layer + phần OCR đã vừa trần).

**Implementation.** `src/rag-worker/app/infrastructure/external/local_parser.py` —
`_make_pymupdf_reader.reader()`:
- Thêm biến đếm chạy `ocr_count` (tổng ảnh-OCR đã gom qua các trang).
- Điều kiện thêm vector-raster: `if vector_ocr and (ocr_count + len(images)) < max_ocr_pages:`
  (trước đây thêm vô điều kiện khi `drawings >= threshold`).
- `ocr_count += len(images)` mỗi trang. Check cuối `total_images() > max_ocr_pages -> raise` GIỮ
  NGUYÊN (chỉ còn fire khi ảnh thiết yếu vượt trần).
- Test `src/rag-worker/tests/infrastructure/test_pymupdf_vector_ocr.py`: +2 case —
  `test_vector_raster_capped_at_budget_does_not_fail` (30 trang chart, trần 25 → total=25, KHÔNG
  raise, 25 trang đầu có raster, còn lại bỏ qua) + `test_essential_images_over_cap_still_raise`
  (30 trang scan → vẫn raise).

**Result.**
- Unit: rag-worker vector-OCR tests 5/5 pass (local, mock fitz).
- CI/CD: ___ (điền sau push)
- Playwright/Langfuse live: ___ (điền sau deploy — re-upload doc chart-heavy 2402.04355v3 → phải
  indexed > 0 chunk; doc-ingest trace SUCCESS thay vì FAILED).
