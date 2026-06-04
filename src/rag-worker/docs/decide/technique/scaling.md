# Scaling / deployment technique

> Mô tả kỹ thuật cụ thể cho [../diagram/scaling.mermaid](../diagram/scaling.mermaid).
> Đây là **góc nhìn vận hành/scale** của *cùng* pipeline mô tả ở [ingestion.md](./ingestion.md) (logic) — không phải pipeline khác. Ký hiệu: **không ★** = bắt buộc theo handoff; **★** = quyết định v2 ngoài/để-ngỏ → ghi `PROPOSED` vào `NEW_REPO_DECISIONS.md`.

## 0. Mục tiêu

Cho phép scale ngang **có điều kiện**: nhiều Parser/Encode worker chạy song song mà không giẫm chân nhau, không mất job, không trả kết quả sai. Handoff KHÔNG cấm scale ngang — nó yêu cầu *làm đúng tiền đề trước* (atomic claim + durable queue) rồi mới scale.

---

## 1. Topology: worker pool 2 tier + queue durable

```
S3 → [event listener ★ | reconciliation scanner] → Queue1 (durable) → claim
   → Tier1: Parser Worker × N  (CPU-heavy, executor riêng)
   → Canonical artifact → Queue2 (durable, Section tasks) → claim
   → Tier2: Encode Worker × M  (I/O-bound) → [shared coalescer → provider/cache]
   → Qdrant + Metadata DB ; failed → DLQ
```

**Tách 2 tier** = tách concurrency theo *loại việc* (parse CPU-heavy vs embed I/O-bound). Mỗi tier có limit + counter riêng; KHÔNG một limit chung (tăng worker mù làm nghẽn nặng hơn).

---

## 2. Atomic claim dưới multi-instance (lõi của scale ngang)

Khi N worker cùng scope nguồn, claim phải atomic (không đọc-rồi-ghi). Xem thuật toán ở [ingestion.md](./ingestion.md) §2. Bổ sung cho scale:

- `claim_id` (attempt id) gắn vào mọi write downstream
- terminal-status guard theo `claim_id` ⇒ job cũ chạy chậm KHÔNG ghi đè job mới
- ★ `version` (object/section) chống stale write khi event out-of-order
- stale reclaim: job `processing` quá hạn (so `updated_at`) được claim lại; check affected_rows khi ghi để không đè bản mới hơn

**Đây là điều kiện để bật >1 instance.** Trước khi có nó, chạy single-instance.

---

## 3. Queue recovery policy

- Queue **durable** (broker thật / bảng pending-job persist), KHÔNG in-memory.
- Restart trước khi claim: job vẫn còn trong queue; nếu mất → reconciliation scanner rediscover.
- Expose: queue depth, số đang chạy, số dropped, scan gần nhất (bắt đầu/kết thúc/lỗi).
- Bắt buộc trước khi scale backlog lớn: durable queue HOẶC pending-job table HOẶC test rediscovery chứng minh file chưa-claim được phát hiện lại.

---

## 4. Shared embedding coalescer — lợi ích & rủi ro HA ★

**Lợi ích:** mỗi worker tự batch → batch nhỏ, tốn tiền/latency. Coalescer dùng chung gom cross-worker → batch lớn + cache content-hash bỏ qua nội dung trùng (footer/disclaimer, reprocess).

**Rủi ro:** là shared component → có thể thành bottleneck / single point of failure / shared mutable state trên đường async.

**Thiết kế HA ★:**
- bounded queue + `max_batch_size` / `max_wait_ms` / `max_tokens_per_batch`
- per-model / per-provider queue (scale theo model)
- graceful drain lúc shutdown (await task active trước khi đóng tài nguyên dùng chung — bug lifecycle v1)
- idempotent response mapping (request ↔ vector đúng chỗ)
- metrics: batch size / wait time / cache-hit rate / provider latency
- cache in-memory không sống qua restart / không cross-process → ★ cache ngoài khi multi-process

---

## 5. DLQ — phân loại để vận hành được

Chỉ "failed" là chưa đủ. Mỗi mục DLQ log:
- `stage` (scan/parse/ocr/split/caption/embed/upsert)
- `error_type` (transient / permanent)
- `retry_count`, `claim_id`, `document_id`, `section_id`
- `error_code` / next_action

**Retry policy:** transient → retry có backoff+jitter; permanent (PDF password, format không hỗ trợ) → KHÔNG retry mãi, đẩy DLQ + alert. Mọi failure vẫn ghi job log + status (không im lặng).

---

## 6. Change detector ở quy mô lớn ★

- **Event primary**: giảm scan thừa, near-realtime — nguồn phải đáng tin + idempotent (`event_id`) + có `object_version` chống out-of-order.
- **Reconciliation scanner**: chu kỳ định kỳ, sửa miss/duplicate, backfill, reconcile orphan/delete.
- Khi corpus rất lớn: list toàn bộ bucket tốn kém → giảm tần suất full-scan, tăng dựa event; vẫn giữ full reconcile định kỳ.
- SLO freshness ("searchable trong X phút") quyết định interval scanner.

---

## 7. Scale từng tier độc lập

| Tín hiệu (từ health/metrics) | Hành động |
|---|---|
| Queue1 depth tăng, Parser bận | scale Parser Worker (Tier 1) / tăng OCR executor |
| Queue2 depth tăng, Encode chờ provider | scale Encode Worker (Tier 2) / tăng batch / kiểm rate-limit |
| Coalescer wait cao, cache-hit thấp | tinh chỉnh batch window / cache ngoài |
| Provider 429 nhiều | giảm concurrency embed, tăng backoff (không tăng worker mù) |

**Nguyên tắc:** phải có metric per-stage để biết bottleneck thật *trước khi* tăng worker.

---

## 8. Cost guardrail ở scale

- trần chi phí mỗi document (số AI/OCR call); document quá đắt → reject/hoãn/giảm cấp
- cache content-hash để không trả tiền lại cho nội dung không đổi
- metric cost theo stage + ngưỡng cảnh báo khi vượt

---

## 9. Capacity / limit config (đề xuất)

```
TIER1_WORKERS / PARSE_EXECUTOR_CONCURRENCY / OCR_EXECUTOR_CONCURRENCY
TIER2_WORKERS / EMBED_CONCURRENCY
QUEUE1_* / QUEUE2_*               # durable backend config
CLAIM_STALE_TIMEOUT
EMBED_MAX_BATCH / MAX_WAIT_MS / MAX_TOKENS
SCANNER_INTERVAL / FULL_RECONCILE_INTERVAL
DLQ_MAX_RETRY / RETRY_BACKOFF
COST_CEILING_PER_DOC / COST_ALERT_THRESHOLD
```

---

## 10. ★ cần ratify (đưa vào NEW_REPO_DECISIONS.md)

- Có chạy multi-instance ngay không (quyết định mức đầu tư claim/version)
- Nguồn event + SLO freshness
- Coalescer HA: per-model scaling + cache ngoài
- Versioning chống stale write
- Durable queue backend cụ thể

## Truy vết handoff
[DAY0_CHECKLIST.md](../../handoff/DAY0_CHECKLIST.md) §1,4,5,6,11,15 · [LESSONS.md](../../handoff/LESSONS.md) §1–4 · [MINDSET.md](../../handoff/MINDSET.md) §5 · [CONSTRAINTS.md](../../handoff/CONSTRAINTS.md) · tổng hợp [../concise.md](../concise.md)
