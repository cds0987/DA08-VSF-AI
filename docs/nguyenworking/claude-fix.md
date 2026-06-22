# claude-fix — Nhật ký FIX lỗi từ eval (claude-querytest.md)

> Mỗi fix: **Motivation → Solution → Implementation (code: làm gì / đổi gì / ở đâu) → Result
> (verify: CI/CD + Playwright đa-case + Langfuse)**. Tuân thủ kiến trúc có sẵn (MOSA + OOP +
> KHÔNG hardcode + mọi call qua AI Router). Mới nhất ở trên.

---

## FIX #2 — Retrieval: "1 doc thống trị top-k" chôn doc nhỏ/đúng → DIVERSITY cap/doc [2026-06-23]

**Motivation.** Eval Section I: retrieval recall yếu — doc nhỏ indexed ĐÚNG nhưng rank=None (bị
chôn); research precision 3/8. Soi 1 query ("similarity thresholds") thấy sources = `2406.17374`
**×5** → 1 document chiếm gần hết top-k, đẩy doc khác (gồm gt) ra ngoài. Đây là gốc cross-doc
precision + small-doc burial (đúng nút thắt #1 của report).

**Solution.** Thêm bước CHỌN ĐA DẠNG DOCUMENT sau rerank (OOP, no-hardcode, configurable, MẶC ĐỊNH
giữ hành vi cũ khi tắt): rerank một POOL rộng hơn (final_k × pool) rồi chọn final_k với tối đa
`rerank_max_per_doc` chunk mỗi document; nếu cap thiếu k thì bù bằng chunk vượt-cap (không trả ít
hơn k). KHÔNG đụng reranker (cohere vẫn nguyên) — chỉ thêm tầng selection ở SearchService.

**Implementation.**
- `src/mcp-service/app/core/search.py`: hàm thuần `diversify_by_document(hits, k, max_per_doc)`
  (cap/doc theo thứ tự score, fill phần dư). `SearchService.rag_search`: nếu `max_per_doc>0` →
  rerank pool = `min(#cands, max(final_k, final_k*diversity_pool))` rồi `diversify_by_document(...)`;
  `max_per_doc<=0` → hành vi cũ (rerank thẳng final_k).
- `src/mcp-service/app/core/config.py`: +2 field `rerank_max_per_doc` (default 0), `rerank_diversity_pool`
  (default 3) + đọc từ retrieval config.
- `src/mcp-service/config.yaml`: `rerank_max_per_doc: ${RERANK_MAX_PER_DOC:-0}`,
  `rerank_diversity_pool: ${RERANK_DIVERSITY_POOL:-3}`.
- `deploy/env/mcp-service.env`: BẬT `RERANK_MAX_PER_DOC=3`, `RERANK_DIVERSITY_POOL=3`.
- Test `tests/test_search_service.py`: +4 (cap+fill, fill-overcap, disabled-passthrough, rag_search
  dùng pool rộng + diversity). 15/15 pass.

**Result.**
- Unit: mcp search/config/rerank **15/15 pass**.
- CI/CD: ___ (sau push)
- Playwright/Langfuse live: ___ (re-query "similarity thresholds" → sources KHÔNG còn 1-doc-×5; +
  re-eval doc nhỏ bị chôn xem recall cải thiện).

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
