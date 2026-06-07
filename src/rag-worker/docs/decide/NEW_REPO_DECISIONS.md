# NEW_REPO_DECISIONS — quyết định v2 (PROPOSED)

> Nơi ratify các `★` rải trong [technique/](./technique/). Template theo [../handoff/NEW_REPO_DECISIONS.md](../handoff/NEW_REPO_DECISIONS.md).
>
> **Tất cả dưới đây là `PROPOSED`** — chưa RATIFIED. Một quyết định chỉ hợp lệ khi có: người chốt + ngày + lý do trong bối cảnh repo mới + trade-off + điều kiện xem lại. Prototype là nguồn học, KHÔNG phải authority.
>
> Khi chốt: đổi `PROPOSED → RATIFIED YYYY-MM-DD (ai)`, và nếu phát sinh ràng buộc cứng → thêm vào [../handoff/CONSTRAINTS.md](../handoff/CONSTRAINTS.md).

---

### D1. Trigger = event PRIMARY + reconciliation scanner SAFETY
**Status:** PROPOSED
**Khác prototype:** prototype polling + in-memory queue → repo này event-driven primary (S3-native/uploader) + scanner reconcile + durable queue.
**Vấn đề:** cần near-realtime khi corpus lớn nhưng không được mất tính độc lập khởi động (bài học event-bus nặng v1).
**Options:**
- A: polling-only — bỏ, latency = chu kỳ scan, list bucket lớn tốn kém.
- B: event-only (không scan) — bỏ, mất dữ liệu khi event miss/sai; coupling khởi động.
- C (đề xuất): **event primary + reconciliation scanner** — scanner reconcile **thẳng S3** làm safety net. Nguồn event có thể S3-native HOẶC team khác, miễn: (1) scanner neo vào S3, (2) event là hint idempotent (event_id)+version, (3) event sai/thiếu → degrade xuống scan không vỡ. *Prefer* S3-native nếu có sẵn.
**Trade-off:** thêm hạ tầng event + cần idempotency (event_id) + version chống out-of-order; nếu dùng event team khác → thêm 1 integration phải bảo trì (degrade-to-scan khi schema đổi).
**Khi nào xem lại:** corpus quá lớn → giảm tần suất full-scan; hoặc nguồn event không đáng tin.
**Cần xác nhận:** nguồn event cụ thể · SLO freshness · có multi-instance ngay không.
→ [technique/ingestion.md](./technique/ingestion.md) §1 · [scaling.md](./technique/scaling.md) §6

**Implementation note (2026-06-07, chưa ratify):**
- Repo hiện đã có **scanner safety-net tối thiểu** ở rag-worker: `STORE_RECONCILE_ENABLED`
  quét trực tiếp bucket `raw/<doc_id>/<file>` qua S3-compatible listing, so với bảng
  `documents`, rồi enqueue lại doc chưa từng được biết.
- `documents` trở thành **sổ đăng ký**; `status=deleted` là tombstone soft-delete để scanner
  không hồi sinh doc đã xóa.
- `doc.status` vì thế được chấp nhận là **best-effort optimization**, không còn là nguồn duy nhất
  đảm bảo eventual ingest. Outbox vẫn là hướng nâng cấp riêng nếu cần handshake tức thời/chắc chắn.

---

### D2. Parser = stateless service (Option 2) + stack MarkItDown + OCR/vision
**Status:** PARTIALLY RATIFIED 2026-06-04 — phần **OCR/vision đi qua AI gateway** đã chốt (xem **R10** trong [../handoff/NEW_REPO_DECISIONS.md](../handoff/NEW_REPO_DECISIONS.md)): OCR là vision LLM gọi qua `core_engine/ocr` (OpenAI SDK), parser chỉ render ảnh bằng PyMuPDF, hybrid theo trang, KHÔNG OCR engine cục bộ. Phần **tách stateless service rời** vẫn `PROPOSED` (bản chạy hiện tại là in-process `LocalFileParser`).
**Khác prototype:** parse chạy in-process trộn với serving → repo này tách **stateless parser pool** ngoài process; main service orchestrate.
**Vấn đề:** parse/OCR CPU-heavy (+remote AI) làm threadpool saturation v1; cần scale CPU độc lập.
**Options:**
- A: parse in-process — bỏ, tranh pool với serving (lỗi v1).
- B: parser tự claim queue/DB/artifact (Option 1) — bỏ, phá ranh giới hexagonal.
- C (đề xuất): **parser thuần convert (Option 2)**; main service giữ claim/retry/write; stack = MarkItDown (text formats) + OCR/vision adapter (scan).
**Trade-off:** thêm network hop + main service quản timeout/retry/staging; parser có nhánh AI (không còn thuần CPU) → 2 concurrency limit.
**Khi nào xem lại:** nếu corpus toàn text nhẹ (OCR hiếm) → có thể in-process bounded executor.
**Ràng buộc mới:** id KHÔNG theo hash markdown (OCR non-deterministic); guard size/allow-list/path-traversal đi theo parser; main service KHÔNG import OpenAI/MarkItDown.
→ [technique/parser.md](./technique/parser.md)

---

### D3. Concurrency model parser = async-bounded-thread HOẶC sync-process-pool
**Status:** PROPOSED
**Vấn đề:** anti-pattern v1 là chung pool + trộn parse với serving; parser tách riêng thì điều kiện đó biến mất.
**Options:**
- A: async + offload thread **chung pool, trộn serving** — bỏ (lỗi v1).
- B (đề xuất, chấp nhận được vì cô lập): **async + bounded thread, request-scoped** trên parser-only server.
- C (đơn giản hơn): **sync N-process pool** — vì việc chính là CPU, async không bắt buộc.
**Trade-off:** B cần quản cancel/drain; C tốn process nhưng đơn giản, né GIL.
**Khi nào xem lại:** nếu CPU pure-Python nặng (GIL-bound) → ưu tiên C/process workers.
→ [technique/parser.md](./technique/parser.md) §4

---

### D4. Embedding service / AI gateway tách (điều kiện multi-instance)
**Status:** PROPOSED
**Khác prototype:** coalescer in-process → repo này tách service chung khi multi-instance.
**Vấn đề:** coalescer in-process per-worker mất cross-worker batch + cache không chia sẻ/không sống qua restart; search & ingest phải cùng embedder.
**Options:**
- A: coalescer in-process — giữ cho MVP single-instance.
- B (đề xuất khi scale): **embedding service async-native** (bounded, per-model queue, cache ngoài, fast-path search + batch-path ingest).
- C (mở rộng): **AI gateway** gom caption+embed+OCR (chung reliability policy) — trade-off concentrate risk.
**Trade-off:** thêm hop (đau search latency → fast-path); shared component → SPOF cần HA.
**Khi nào xem lại:** khi chạy >1 instance HOẶC rate-limit thành bottleneck.
→ [technique/embedding.md](./technique/embedding.md)

---

### D5. Pluggable execution + fallback policy (remote/local)
**Status:** PROPOSED
**Vấn đề:** muốn linh hoạt đẩy task sang helper, fallback khi helper sập — mà không tái tạo lỗi v1.
**Options:**
- A: fallback compute nặng về main mặc định — bỏ, cascade threadpool saturation.
- B (đề xuất): **contract + Remote/Local adapter + router có policy**; circuit OPEN → **pause claim** queue tương ứng (KHÔNG hot-requeue loop, KHÔNG đổ về main); task đã-claim-mà-lỗi → release+backoff; search query-embed = **bounded local fallback CHỈ khi vector-compatible**; circuit-breaker + health-mode visible.
**Trade-off:** thêm router/policy + pause-consumer logic; phải giữ tường minh (không magic).
**Ràng buộc mới:** fallback visible qua health; local fallback bounded + cùng dimension/space Qdrant; circuit OPEN ngừng claim thay vì requeue nóng; policy là config per-capability+path.
**Khi nào xem lại:** khi thêm capability mới hoặc đổi SLA availability.
→ [technique/execution-fallback.md](./technique/execution-fallback.md)

---

### D6. Versioning chống stale-write (event out-of-order)
**Status:** PROPOSED
**Vấn đề:** event-driven → out-of-order; job cũ chạy chậm có thể ghi đè bản mới.
**Đề xuất:** thêm `object_version`/`section_version`; upsert guard theo `claim_id/attempt + version`; KHÔNG ghi đè bản mới hơn.
**Trade-off:** thêm cột version + so sánh khi ghi.
**Khi nào xem lại:** nếu giữ polling-only (out-of-order hiếm) thì có thể hoãn.
→ [technique/ingestion.md](./technique/ingestion.md) §7 · [scaling.md](./technique/scaling.md) §2

---

### D7. Payload content_ref cho section lớn (+ caption-only vs rerank)
**Status:** PROPOSED
**Vấn đề:** section lớn → full content trong Qdrant payload làm store nặng; caption-only có thể giảm recall chi tiết.
**Đề xuất:** section > ngưỡng → payload lưu `content_ref` + preview, search **resolve về full content** (giữ contract); cân nhắc **rerank/hybrid** bù caption-only.
**Trade-off:** thêm read-dependency vào artifact lúc search; rerank thêm latency.
🔴 **Ràng buộc cứng phải giữ:** response vẫn trả *nội dung đầy đủ* (content_ref chỉ là tối ưu lưu trữ).
**Khi nào xem lại:** đo recall caption-only trên corpus thật trước khi quyết hybrid.
→ [technique/search.md](./technique/search.md) §4,5,6

---

### D8. Backend abstraction + execution modes (MVP-first → scale)
**Status:** PROPOSED
**Khác prototype:** prototype gọi thẳng SDK trong main → repo này orchestrator gọi qua capability interface (Local/Remote backend), mode tường minh.
**Vấn đề:** muốn chạy được với 1 server (MVP) nhưng không khóa chết vào 1 server; thêm server thì scale, không rewrite core.
**Options:**
- A: hardcode `parse_file()` gọi MarkItDown trong main process — bỏ, khóa vào local + CPU vào main.
- B (đề xuất): **capability interface ngày 1** (`ParserBackend` Local/Remote) + mode `single-node`/`hybrid`/`distributed` explicit.
**Phân phối nhiều server — đừng mặc định tự viết scheduler:**
- server đồng nhất → **LB / K8s Service** hoặc **pull-queue** (zero registry tự viết) ← default.
- server **heterogeneous capability** → mới cần **capability registry + capacity scheduler + heartbeat**.
**Trade-off:** interface = ít boilerplate (chấp nhận); registry/scheduler = shared state nặng (chỉ build khi cần).
**Ràng buộc mới:** heartbeat KHÔNG phải nguồn correctness (correctness = claim+idempotent); mode explicit không thừa kế ngầm; main KHÔNG import SDK.
**Khi nào xem lại:** khi server bắt đầu khác capability → nâng router lên capability-aware.
→ [technique/execution-fallback.md](./technique/execution-fallback.md) §4b,4c

---

## Trạng thái tổng
| ID | Quyết định | Status | Điều kiện ratify |
|---|---|---|---|
| D1 | Trigger hybrid | PROPOSED | nguồn event + SLO + multi-instance? |
| D2 | Parser stateless service + OCR/vision | OCR-qua-gateway **RATIFIED** (R10); tách service rời còn PROPOSED | xác nhận tách service + ngưỡng OCR |
| D3 | Concurrency model parser | PROPOSED | đo GIL-bound? |
| D4 | Embedding/AI gateway tách | PROPOSED | khi >1 instance |
| D5 | Pluggable execution + fallback | PROPOSED | bảng policy per-capability |
| D6 | Versioning anti-stale-write | PROPOSED | nếu event-driven |
| D7 | content_ref + rerank | PROPOSED | đo recall corpus thật |
| D8 | Backend abstraction + execution modes | PROPOSED | registry chỉ khi server heterogeneous |
