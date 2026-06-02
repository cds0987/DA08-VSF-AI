# Parser service technique — stateless parse/convert

> Thành phần: **Stateless Parser Server** (adapter ngoài-process cho capability `parse`).
> Grounded trong [../../handoff/](../../handoff/). **Không ★** = bắt buộc theo handoff; **★** = quyết định v2 → ghi `PROPOSED` vào [../NEW_REPO_DECISIONS.md](../NEW_REPO_DECISIONS.md).

## 0. Vai trò

CPU/convert thuần: `file ref → canonical Markdown (+ metadata)`. **Không** chứa state lâu dài, **không** biết queue/DB/Qdrant. Đây là một **adapter** (ngoài process) sau contract `Parser`; orchestration/claim/retry/write nằm ở **main ingestion service** (Option 2).

```
Main Ingestion (claim Queue1) → POST /parse → Stateless Parser → markdown/sections
                              → ghi canonical artifact → tạo Section tasks (Queue2)
```

Vì sao Option 2 (parser thuần) thắng Option 1 (parser tự claim queue/DB): giữ parser sạch = giữ đúng ranh giới hexagonal (use-case không lẫn adapter); Option 1 tái lập flat-structure v1.

## 1. API

```
POST /parse
in : { object_key | presigned_url, file_type, options, document_id, version }
out: { status, markdown | artifact_key, sections[], pages, warnings[], content_hash }
```

- **Truyền file ref, KHÔNG truyền binary lớn**: object_key / presigned URL; parser tự pull từ S3. Tránh double-transfer + timeout.
- **Output lớn → 2 cách:**
  - **A (file nhỏ/vừa):** trả `markdown` trực tiếp.
  - **B (file lớn):** parser upload markdown vào **staging prefix** rồi trả `artifact_key`. Vẫn stateless (ghi xong là quên).
  - 🔴 Cách B **ghi staging, KHÔNG ghi canonical**. Main service mới promote sang canonical address với **write-order** (mark→overwrite→prune→complete). Giữ invariant consistency ở MỘT nơi (handoff: tách prefix cho artifact dẫn xuất).

## 2. Stack ★ — MarkItDown + OCR/vision

- **MarkItDown (Microsoft)** cho format có cấu trúc/text (DOCX/PPTX/HTML/PDF-có-text) → Markdown.
- **OCR/vision adapter** (vd OpenAI vision hoặc OCR engine) cho scan/ảnh không text-layer.
- Dùng vendor SDK (OpenAI client, MarkItDown) **trong parser là ĐÚNG chỗ** — parser là adapter. Cấm là **main service** import các SDK này.

**Phân biệt 2 loại "caption" — đừng gộp:**
- *Parse-time image description* (MarkItDown LLM mô tả ảnh → nhúng vào Markdown): **nội dung artifact**, ở parser.
- *Index-time caption* (nén ý nghĩa section để embed): ở **Tier 2 Index**, KHÔNG ở parser.

## 3. Hai concurrency limit (cheap vs expensive)

OpenAI làm parser **không còn thuần CPU**. Tách rõ:

| Việc | Loại | Scale theo | Cần |
|---|---|---|---|
| MarkItDown convert text formats | CPU thuần | CPU usage | bounded pool ~#core |
| OCR/vision qua provider | I/O + AI, đắt | rate-limit / cost | retry+backoff+jitter, cost ceiling, semaphore riêng |

Không một limit chung (bài học v1 §4.7).

## 4. Concurrency model ★ — async-bọc-thread CHẤP NHẬN ĐƯỢC ở đây

Anti-pattern v1 là *chung pool + trộn parse với serving trong một process*. Parser tách riêng → không có serving để bị bỏ đói → **offload blocking sang threadpool là hợp lệ**. Đây đúng là phương án "worker ngoài" handoff cho phép ([DAY0 §1](../../handoff/DAY0_CHECKLIST.md)).

Điều kiện:
- pool **bounded** (CPU pool ~#core; semaphore riêng cho OCR remote)
- offload **theo phạm vi request**, await trong request — KHÔNG fire-and-forget fan-out (tránh bug lifecycle v1)
- cancel/timeout sạch, giải phóng slot ở `finally`
- ⚠ **GIL (Python):** thread chỉ song song thật khi lib nhả GIL (lxml/pillow/pdf C-ext) hoặc cho network OCR; CPU pure-Python nặng → cần **process workers**.
- Thực tế: vì việc chính là CPU, **mô hình sync N-process** còn đơn giản hơn async — async không bắt buộc ở đây.

## 5. Guards (đi theo parser — đừng để rớt khi tách service)

Parser giờ là I/O boundary đọc nguồn → bắt buộc (CONSTRAINTS §2 security):
- **validate size TRƯỚC khi đọc body** vào memory
- allow-list bucket/prefix nguồn · chặn path traversal
- limit: `max_file_size`, `max_pages`, `max_ocr_pages`, `max_parse_seconds`

## 6. Determinism — id KHÔNG theo hash markdown

OCR/LLM output không byte-deterministic. → `section_id = f(document_id, order)`, `document_id = f(địa chỉ nguồn)`. **content_hash chỉ dùng cho cache + change-detection**, KHÔNG làm id (nếu không, mỗi lần OCR lệch là vỡ idempotent reprocess).

## 7. Cross-cutting

- **Config validation startup**: provider/base URL/model/key của OCR/vision (v1 đau OpenRouter base URL + model format).
- **Cost guardrail**: cache skip theo source content_hash; trần chi phí/doc; `max_ocr_pages`.
- **Lazy import optional deps**: MarkItDown kéo dep nặng theo format → import lazy trong method/khởi tạo, skip-nếu-thiếu, KHÔNG top-level.
- **Health**: parser pool down ⇒ main service báo **degraded** (không im lặng). Parser phơi `/health` để main probe.
- **Recovery**: parser chết giữa chừng → main không nhận markdown → task retry từ Queue 1 (claim ở main). Idempotent nhờ id deterministic.

## 8. Scaling

`Parser Pool`: CPU-optimized, autoscale theo **Queue1 depth / CPU**. Tách khỏi `Index Pool` (autoscale theo Queue2 / rate-limit).

## 9. ★ cần ratify → [../NEW_REPO_DECISIONS.md](../NEW_REPO_DECISIONS.md)
- Parser = stateless service (Option 2) + stack MarkItDown + OCR/vision
- Output A (inline) vs B (staging upload) theo ngưỡng kích thước
- Concurrency model parser (sync-process-pool vs async-bounded-thread)

## Truy vết handoff
[LESSONS.md](../../handoff/LESSONS.md) §2,4 · [CONSTRAINTS.md](../../handoff/CONSTRAINTS.md) §1,2 · [DAY0_CHECKLIST.md](../../handoff/DAY0_CHECKLIST.md) §1,7,9,15 · [ingestion.md](./ingestion.md) §3,4
