# Ingestion technique — luồng GHI

> Mô tả kỹ thuật cụ thể cho [../diagram/ingestion.mermaid](../diagram/ingestion.mermaid).
> Grounded trong [../../handoff/](../../handoff/). Ký hiệu: **không ★** = bắt buộc theo handoff; **★** = quyết định v2 ngoài/để-ngỏ trong handoff → phải ghi `PROPOSED` vào `NEW_REPO_DECISIONS.md` trước khi chốt.

## 0. Mục tiêu

Biến raw document trên object store thành section có nghĩa, embed *caption* của section, index *full content* + lineage vào vector store — idempotent, durable, fail-closed. Tính đúng dữ liệu (consistency) ưu tiên trước throughput.

---

## 1. Change detector (event PRIMARY + reconciliation SAFETY) ★

Hai đường vào, cùng đổ về một durable queue.

**Event listener (primary) ★** — nguồn event có thể là S3-native (EventBridge/SQS), uploader bạn sở hữu, **hoặc event của team khác** — miễn thỏa 3 điều kiện làm nó an toàn (chính reconciliation scanner trung hòa nỗi đau coupling v1):

1. **Scanner reconcile thẳng S3** (nơi data thật nằm), KHÔNG reconcile với DB/API team kia → giữ độc lập khởi động.
2. **Event chỉ là hint, không phải nguồn sự thật**: idempotent (`event_id`), out-of-order-safe (`version`); hệ vẫn đúng kể cả khi mất 100% event.
3. **Event sai/thiếu → degrade xuống scan, KHÔNG vỡ** (schema họ đổi thì rơi về scan, không chết).

*Prefer* S3-native khi có sẵn (bớt 1 integration + tránh race "event tới trước khi object readable"). Bài học v1 ([../../handoff/LESSONS.md](../../handoff/LESSONS.md) §1) là về *operational coupling* (không start được nếu thiếu event) — scanner-neo-S3 đã xử lý, nên event team khác được phép làm accelerator. Event payload tối thiểu:

```json
{
  "event_id": "...",            // idempotency key
  "event_type": "created|updated|deleted",
  "document_id": "...",         // deterministic theo địa chỉ nguồn
  "s3_key": "...",
  "object_version": "...",      // ★ chống out-of-order
  "etag": "...",
  "content_hash": "...",
  "occurred_at": "..."
}
```

**Reconciliation scanner (safety net)** — periodic list + so với Metadata DB, phân nhánh NEW / UPDATED / DELETED, sửa miss/duplicate/out-of-order của event, reconcile orphan (document đã xoá/đổi tên ở nguồn). Đây là cơ chế bắt buộc vì event không đáng tin tuyệt đối; cũng dùng cho backfill/migration.

**Đặc tính:** event = near-realtime; scanner = không-thể-miss-âm-thầm. Idempotency dựa `event_id` + deterministic `document_id` + atomic claim (mục 2) ⇒ duplicate event tự khử.

---

## 2. Durable job store + atomic claim

**Job store durable** — pending-job persist, KHÔNG in-memory (v1 mất job khi restart trước claim — [../../handoff/DAY0_CHECKLIST.md](../../handoff/DAY0_CHECKLIST.md) §4).

**Atomic claim** — một đơn vị công việc chỉ có một chủ tại một thời điểm. Thuật toán (conditional update, không đọc-rồi-ghi):

```sql
UPDATE jobs
SET status='processing', claim_id=:new_claim, updated_at=now(), attempt=attempt+1
WHERE document_id=:id
  AND (status IN ('pending','stale') OR claim_id IS NULL)
-- claim thành công ⇔ affected_rows = 1
```

**Terminal-status guard** — khi ghi trạng thái cuối phải khớp chủ hiện hành:

```sql
UPDATE jobs SET status=:final
WHERE document_id=:id AND claim_id=:my_claim
-- affected_rows=0 ⇒ job đã bị reclaim, KHÔNG ghi đè
```

`updated_at` đổi khi acquire ⇒ stale-detection có căn cứ. (Chi tiet schema/scale: [scaling.md](./scaling.md) §2.)

**Tách claim theo loại queue** — Q1 (file) và Q2 (section) có schema/TTL/retry KHÁC nhau, không dùng chung một cơ chế claim:
- **File Claim (Q1):** TTL dài (~10–30m) vì parse/OCR lâu.
- **Section Claim (Q2):** TTL ngắn (~1–5m) vì embed/upsert nhanh.

Orchestrator chạy **2 mode tách biệt**: claim từ Q1 → *parse mode* (gọi parser → write artifact → enqueue Q2); claim từ Q2 → *index mode* (caption → embed → upsert). Một task KHÔNG đi qua cả parse lẫn embed trong một lần claim.

---

## 3. Tier 1 — Parse (CPU-heavy, executor RIÊNG)

Chạy trên executor riêng có giới hạn, KHÔNG dùng chung pool với serving (tránh async nửa vời của v1).

**I/O guard dùng chung (bắt buộc, trước mọi đọc):**
- allow-list nguồn (chặn truy cập chéo ngoài phạm vi)
- chặn path traversal
- **validate size TRƯỚC khi đọc body vào memory** (tránh OOM)
- guard này dùng chung cho cả path sync và async

**Parse / Convert / OCR:**
- tách *loại rẻ* (text, sync) khỏi *loại đắt* (visual/OCR remote) — khác executor/concurrency
- trần chi phí mỗi document (số AI/OCR call tối đa) ★; vượt → reject/hoãn/giảm cấp, không xử lý mù
- cache skip theo content-hash: nội dung không đổi không parse/OCR lại

---

## 4. Canonical artifact (source-of-truth sau parse)

Sau parse, ghi **một** Markdown artifact tại địa chỉ ổn định `{prefix}/{document_id}`. Downstream (split/caption/embed) chỉ đọc artifact, không đọc lại raw bytes.

**Vì sao:** đổi splitter/embedder/prompt → replay downstream *không* phải parse/OCR lại (bước đắt nhất); inspect/debug được; lineage `nguồn → artifact → section → vector` truy ngược được.

---

## 5. Section split (đơn vị NGHĨA, không token-chunk)

Chia theo cấu trúc nghĩa do tác giả tài liệu tạo (heading), KHÔNG cắt token cố định + overlap. Mỗi section mang:

```
section_id          # deterministic = f(document_id, order)
document_id
heading_path        # ["A","B","C"]
section_order
content_hash        # cho cache + change detection
parent_section_id?  # ★ nếu cần cây
position_start/end? # ★ phục vụ resolve content_ref (xem search.md)
```

**Length guard:** section quá dài (tài liệu thiếu cấu trúc) → sub-split theo ranh giới nhỏ hơn, giữ `heading_path` + thứ tự. Ngưỡng configurable.

---

## 6. Tier 2 — Encode / Upsert (I/O-bound, limit RIÊNG)

**Caption** — sinh tóm tắt ngắn biểu diễn *ý nghĩa nén* của section (khử vocabulary mismatch giữa câu hỏi tự nhiên và văn phong tài liệu). Lưu kèm để biết khi nào cần re-embed:
- `caption`, `caption_model`, `prompt_version`, `caption_hash`
- reliability policy đồng nhất cho mọi AI call: retry + backoff + jitter

> ⚠ Caption trở thành thành phần quyết định recall. Caption tệ ⇒ search lệch dù full content vẫn nằm trong payload. Rủi ro + cách bù (rerank/hybrid) ở [search.md](./search.md) §4. Đây là Open Question caption-only vs hybrid.

**Embedding-coalescer DÙNG CHUNG** — gom request cross-worker thành batch lớn, flush theo *size* HOẶC *time-window*; cache theo `content_hash` để skip re-embed. Bounds bắt buộc:
- `max_batch_size`, `max_wait_ms`, `max_tokens_per_batch`
- bounded queue, graceful drain lúc shutdown (await task active trước khi đóng tài nguyên)
- metrics: batch size / wait / cache-hit / provider latency
- cache in-memory không sống qua restart / không chia sẻ cross-process → Open Question cache ngoài khi multi-process

**Embed** — embed *caption*, KHÔNG embed raw/full content.

---

## 7. Write order (atomic-safe replace)

Thứ tự bất biến, KHÔNG delete-rồi-recreate:

```
1. mark "đang xử lý"
2. ghi-đè dữ liệu chính (id deterministic)   ← upsert vector + payload, doc/section
3. prune phần thừa (section dư từ bản cũ dài hơn)
4. mark "hoàn tất"   (chỉ khi 2+5 thành công)
5. cập nhật metadata cuối
6. ghi job log
```

**Guard chống stale write:** mọi upsert downstream kèm điều kiện `claim_id`/`attempt` hiện hành khớp + `status` chưa terminal. ★ Với event out-of-order, thêm `version` (object_version/section_version) để job cũ chạy chậm KHÔNG ghi đè bản mới.

---

## 8. Stores

**Vector store / Qdrant:**
- `vector = embedding(caption)`
- `payload` chứa đủ field để dựng response schema (chuẩn ở [search.md](./search.md) §6): `unit_id` · `document_id` · `display_name` · `caption` · `content` (full) · `heading_path` · `lineage.artifact_uri` · `lineage.source_uri`
- `score` do search sinh lúc truy vấn (không lưu sẵn); `correlation_id` gắn theo request
- `id` deterministic dẫn xuất từ `section_id`
- collection/index id **encode dimension** (đổi dimension = migration, không config edit)
- ★ section quá lớn: payload lưu `content_ref` + preview thay vì `content` — *nhưng* search phải resolve về full content để giữ contract (xem [search.md](./search.md) §5)

**Metadata DB:**
- document/section records, `caption_model`/`prompt_version`, ★`*_version`
- job log + **retention/prune + index cột thời gian** (v1 job-log phình vô hạn)

---

## 9. Failure path (KHÔNG im lặng)

- mark document `failed` + job log `status=failed`
- phân loại: `stage` (scan/parse/ocr/split/caption/embed/upsert), `error_type` (transient/permanent), `retry_count`
- permanent (vd PDF password-protected) KHÔNG retry mãi → DLQ
- giải phóng slot/future ở `finally` (tránh leak concurrency)

---

## 10. Cross-cutting (bắt buộc trước production)

| Mục | Yêu cầu |
|---|---|
| Config validation | startup fail-fast: provider+baseURL+model · model+dimension+index · backend+credential |
| Health/readiness | fail-closed; degraded ⇒ unhealthy + backend identity + lý do; lộ queue depth/running/dropped/scan/coalescer |
| Deploy verify | pin SHA/digest (không `latest`); verify image + health + migration sau rollout |
| Observability | correlation field từ đầu: document_id / stage / duration / backend name |
| Retention/lifecycle | bảng "loại dữ liệu → owner → retention → cleanup" |
| Cost guardrail | trần chi phí AI/OCR/embedding + metric cost theo stage + policy khi vượt |

---

## 11. Config keys (đề xuất, cần đặt tên thật ở repo mới)

```
PARSE_EXECUTOR_CONCURRENCY      # tách khỏi serving
OCR_EXECUTOR_CONCURRENCY        # riêng cho loại đắt
MAX_SOURCE_SIZE_BYTES           # size guard trước khi đọc
SECTION_MAX_LEN / SUBSPLIT_LEN
CAPTION_MODEL / CAPTION_PROMPT_VERSION
EMBED_MAX_BATCH / EMBED_MAX_WAIT_MS / EMBED_MAX_TOKENS
EMBED_MODEL / EMBED_DIMENSION    # validate cùng index id
COST_CEILING_PER_DOC
JOBLOG_RETENTION_DAYS
```

---

## 12. ★ cần ratify (đưa vào NEW_REPO_DECISIONS.md)

- Trigger: nguồn event cụ thể + SLO freshness + có multi-instance ngay không
- Caption-only vs hybrid embed
- Versioning fields chống stale write
- Payload `content_ref` vs full content + ngưỡng kích thước
- Cache embedding ngoài khi multi-process

## Truy vết handoff
[CONSTRAINTS.md](../../handoff/CONSTRAINTS.md) §1–4 · [DAY0_CHECKLIST.md](../../handoff/DAY0_CHECKLIST.md) §1–16 · [LESSONS.md](../../handoff/LESSONS.md) · [MINDSET.md](../../handoff/MINDSET.md) · tổng hợp [../concise.md](../concise.md)
