# claude-fix — Nhật ký FIX lỗi từ eval (claude-querytest.md)

> Mỗi fix: **Motivation → Solution → Implementation (code: làm gì / đổi gì / ở đâu) → Result
> (verify: CI/CD + Playwright đa-case + Langfuse)**. Tuân thủ kiến trúc có sẵn (MOSA + OOP +
> KHÔNG hardcode + mọi call qua AI Router). Mới nhất ở trên.

---

## FIX #1 — Doc nhiều ảnh FAIL ingest (vượt MAX_OCR_PAGES) → GRACEFUL CAP [2026-06-23]

**Motivation.** Eval Section I bắt: `2402.04355v3.pdf` fail ingest (0 chunk) — *"requires OCR on
43 images but exceeds MAX_OCR_PAGES(25)"*. Hai tầng:
1. Fix vector-rasterize (Section I) thêm 1 raster/trang-chart → đẩy tổng vượt trần.
2. Gốc sâu hơn: cơ chế cũ **raise** khi tổng ảnh > trần → doc FAIL **0 chunk**, mất CẢ text-layer
   (vốn parse tốt). Re-upload sau khi cap vector-raster vẫn fail "38 images" → doc có 38 ảnh
   EMBEDDED thiết yếu > 25. ⇒ raise-on-overflow là bug: làm mất nguyên 1 doc.

**Solution.** **Graceful cap-and-continue** (KHÔNG raise nữa): OCR tới đúng trần `MAX_OCR_PAGES`
rồi BỎ QUA ảnh dư; text-layer + phần OCR vừa trần vẫn ingest. Cost vẫn bounded = trần. Ưu tiên ngầm
theo trang: scan/embedded (thiết yếu) trước vector-raster (bổ sung). Log số ảnh bị bỏ.

**Implementation.** `src/rag-worker/app/infrastructure/external/local_parser.py`:
- Thêm `import logging` + `logger`.
- `_make_pymupdf_reader.reader()`: biến đếm chạy `ocr_count` + `dropped`.
  - Trang scan: thêm raster CHỈ khi `ocr_count < max_ocr_pages`, else `dropped++`.
  - Ảnh nhúng: trong loop, `if ocr_count + len(images) >= max_ocr_pages: dropped++; continue`.
  - Vector-raster (bổ sung): chỉ khi `(ocr_count + len(images)) < max_ocr_pages`.
  - **BỎ** `if total_images() > max_ocr_pages: raise ...` → thay bằng `logger.warning(ocr_budget_capped...)`.
- Test `tests/infrastructure/test_pymupdf_vector_ocr.py`: 6 case —
  vector-raster-capped, scan-over-cap-capped (KHÔNG raise, total=25), embedded-over-cap-capped
  (40 ảnh→25, text giữ), + 3 case cũ (vector trigger/disable/scan). Fake `extract_image` trả ảnh hợp lệ.

**Result.** ✅ XONG.
- Unit: rag-worker vector-OCR tests **6/6 pass**.
- CI/CD: 2 commit (`1ef04e7` budget vector-raster, `214296e` graceful cap) đều **xanh + deploy**.
- Playwright live: re-upload `2402.04355v3.pdf` (38 ảnh, TRƯỚC: fail 0 chunk "exceeds MAX_OCR_PAGES")
  → SAU: **indexed = 283 chunks** (OCR 25 ảnh đầu + giữ text-layer). Doc không còn bị mất.
