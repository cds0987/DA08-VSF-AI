# Embedding / AI gateway technique

> Thành phần: **Embedding Service** (mở rộng: **AI gateway** gom mọi outbound AI call).
> Grounded trong [../../handoff/](../../handoff/). **Không ★** = bắt buộc; **★** = quyết định v2 → [../NEW_REPO_DECISIONS.md](../NEW_REPO_DECISIONS.md).

## 0. Vì sao tách (khác lý do của parser)

- Parser tách vì **CPU**. Embedding tách vì **shared-state + batching + rate-limit tập trung**.
- Coalescer là shared mutable state; in-process per-worker → mỗi worker batch nhỏ, **cache không chia sẻ**, mất khi restart ([MINDSET §3](../../handoff/MINDSET.md)). Nhiều index worker ⇒ muốn batch thật + cache thật ⇒ coalescer phải là **service dùng chung**.
- **Search query-embed và ingest caption-embed phải dùng CÙNG embedder/dimension** (lệch là recall vô nghĩa). Một service chung ⇒ đảm bảo bằng kiến trúc.

## 1. Concurrency model — async-native (NGƯỢC parser)

Embedding là **I/O-bound** → đây đúng là chỗ async-native trả công: nhiều call provider đồng thời (gather + semaphore), batching. Khác parser (CPU, sync-pool đủ).

## 2. API (2 chế độ)

```
POST /embed
  batch-path  : ingest — gom theo size HOẶC time-window, tối ưu throughput/cost
  fast-path   : search query — embed ngay, vẫn qua cache + rate-limit (giảm latency hop)
```

- input: `{ texts[] | text, model }` ; cache key = `content_hash`
- output: `{ vectors[] }` ; idempotent response mapping (request ↔ vector đúng chỗ)

## 3. HA — vì là shared component (SPOF/bottleneck)

Bắt buộc (xem [scaling.md](./scaling.md) §4):
- bounded queue · `max_batch / max_wait_ms / max_tokens`
- **per-model / per-provider queue** (scale theo model; tránh dimension mismatch)
- graceful drain lúc shutdown (await task active trước khi đóng tài nguyên — bug lifecycle v1)
- metrics: batch size / wait / cache-hit / provider latency / 429 rate
- **cache ngoài (Redis)** nếu multi-replica (in-memory không chia sẻ/không sống qua restart)

## 4. Model ↔ dimension routing

- service route theo `model`; dimension phải khớp **collection đích** (index id encode dimension).
- đổi model/dimension = **migration** (reindex/cutover), KHÔNG config edit (CONSTRAINTS §2).
- **config validation startup**: provider + base URL + model + key (v1 đau OpenRouter base URL/model format).
- 🔴 **Local fallback (search) phải vector-compatible:** local embedder chỉ dùng được nếu sinh vector **cùng model/dimension/space** với vector đã index trong Qdrant. Khác model (vd ingest `text-embedding-3-large` 3072d, fallback `bge-small` 384d) ⇒ query vào sai không gian = rác. Nếu không có model local tương thích → KHÔNG fallback local, để search degraded/fail-closed thay vì trả sai.

## 4b. Cache phải SHARED (không local-only)

Gateway là pool × M ⇒ cache in-memory trên từng instance kém hiệu quả (instance A có, B không → request trùng vẫn embed lại). Dùng **cache chung**: Redis HOẶC bảng `embedding_cache` (key = `content_hash`). Khớp Open Question handoff "cache ngoài khi multi-process" (MINDSET §3).

## 5. Mở rộng — AI gateway ★

Caption-gen (LLM) và OCR-vision **cùng profile** với embed: AI call · I/O · rate-limited · cacheable · cần *reliability policy đồng nhất* ([LESSONS §4.9](../../handoff/LESSONS.md): mọi AI call cùng retry+backoff+jitter+cache).

→ Có thể gom **một AI gateway** = một chỗ duy nhất cho rate-limit + retry + cost metering + config validation + cache, phục vụ `caption · embed · (OCR remote)`, với **per-capability queue** (chung policy, cô lập theo capability).

Trade-off: gateway tập trung policy nhưng **concentrate risk** → phải HA. Tách riêng từng service thì cô lập lỗi tốt hơn nhưng lặp policy.

## 6. Khi nào tách — khi nào KHÔNG

- **MVP single-instance**: giữ coalescer **in-process**, đừng tách (tính đúng trước throughput; tránh service thừa).
- **Tách khi**: multi-process/multi-instance, HOẶC rate-limit thành bottleneck, HOẶC cần cache sống qua restart.
- → **★ quyết định theo scale**, điều kiện ratify: chạy >1 instance.

## 7. Đặc tính vận hành
- ingest: throughput-first (batch lớn) ; search: latency-first (fast-path).
- backpressure: nếu provider 429 → giảm concurrency + tăng backoff (KHÔNG tăng worker mù).
- health lộ áp lực embed của search (DAY0 §6).

## 8. ★ cần ratify → [../NEW_REPO_DECISIONS.md](../NEW_REPO_DECISIONS.md)
- Embedding service tách (điều kiện multi-instance) + cache ngoài
- AI gateway gom caption/embed/OCR vs service riêng từng cái

## Truy vết handoff
[MINDSET.md](../../handoff/MINDSET.md) §3 · [LESSONS.md](../../handoff/LESSONS.md) §3,4.9 · [DAY0_CHECKLIST.md](../../handoff/DAY0_CHECKLIST.md) §6,10,12 · [CONSTRAINTS.md](../../handoff/CONSTRAINTS.md) §2
