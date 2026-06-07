# GAP v8 — rag-worker: phân loại lỗi AI, độ bền artifact, doc lớn & observability

Scope: `src/rag-worker` — engine ingest, embedding/caption provider, retry policy, Qdrant
write path, artifact store, job lifecycle, reconciler.
Grounding: deep code review tại `nguyendev` HEAD (2026-06-07) — đọc entrypoint → runtime →
worker → use-case → engine → provider (AI gateway) → Qdrant adapter → reconciler.
Status: **OPEN** — các gap dưới đây CHƯA fix; KHÔNG trùng G7 (G7-1..G7-18 đã CLOSED).

> Quy ước trạng thái trong file này:
> - `OPEN` = đã xác minh trong code hiện tại và chưa có implementation.
> - `CHỐT` = đã chốt hướng xử lý/decision, nhưng **chưa có nghĩa là đã code**.

> Lưu ý phạm vi: gap8 **không** lặp lại G7. Cụ thể đã đóng ở G7 và KHÔNG mở lại:
> embed-batch chia lô (G7-14), `asyncio.wait_for` timeout (G7-4), caption song song +
> semaphore (G7-5), `SKIP LOCKED` (G7-9), doc.status outbox sweep (G7-8/G7-16),
> re-ingest rỗng prune (G7-17). gap8 là lớp kế tiếp: **biên độ điều khiển lỗi AI**,
> **độ bền artifact**, **doc cực lớn** và **đo lường**.

---

## Điểm mạnh giữ nguyên (không regress khi fix)

- **Retry+backoff+jitter đồng nhất** cho mọi call AI qua `retry_async` (`core_engine/ai/base.py:183`).
- **Idempotent ingest**: `chunk_id` ổn định + upsert-then-prune (`core_engine/engine.py:151-154`).
- **Job queue**: claim optimistic-lock + `SKIP LOCKED` + heartbeat + stale-reaper.
  (⚠️ partial unique index `ux_ingest_jobs_active_document_id` TỪNG vô hiệu do lệch case
  predicate — xem **G8-12**, đã fix bởi `5add77a`/migration 0005.)
- **Hai cơ chế độ bền**: store reconciler (no-row) + doc.status outbox sweep (tín hiệu mất).
- **S3 download 5 lớp guard** chống OOM/đầy đĩa (`app/infrastructure/external/s3_parser.py:232`).

---

## Đối chiếu code hiện tại (2026-06-07)

Các điểm dưới đây đã được re-check trực tiếp trên code để tránh drift giữa doc và implementation:

- `core_engine/ai/base.py`: `retry_async` vẫn đang `except Exception` và retry toàn bộ lỗi. G8-2 còn mở.
- `app/application/use_cases/ingestion/ingest_document_use_case.py`: lỗi ingest vẫn đi vào `fail_job(...)` rồi trả job `FAILED`; chưa có phân loại transient/permanent. G8-1 còn mở phần classification/metric.
- `app/application/use_cases/ingestion/store_reconciler.py`: reconciler vẫn `continue` với **mọi** document đã có row; chưa retry row `FAILED`. G8-4 còn mở.
- `core_engine/vectorstore/providers/qdrant/remote.py`: `list_chunk_ids_by_document()` vẫn scroll đúng 1 trang `limit=10000`; `upsert_many()` vẫn gửi một request duy nhất. G8-5/G8-6 còn mở.
- `app/interfaces/api/runtime.py`: `build_artifact_store()` vẫn trả `LocalArtifactStore()`; `/healthz` chưa nhúng queue/caption-fallback counters; chưa có `/metrics`. G8-7/G8-9 còn mở.
- `app/application/use_cases/ingestion/ingest_document_use_case.py`: heartbeat mất lease vẫn chỉ log `ingest_claim_heartbeat_lost` rồi return, chưa cancel ingest. G8-8 còn mở.
- `core_engine/engine.py`: `caption_ms` vẫn cộng `elapsed_ms` của từng task caption song song, nên metric vẫn bị cộng chồng. G8-11 còn mở.

---

## Gaps đã xác minh

| ID | Mức | Vấn đề | File / dòng | Trạng thái |
|----|-----|---------|-------------|------------|
| G8-1 | **P1** | AI outage kéo dài (> ~15s, hết retry) → job FAILED terminal | `ingest_document_use_case.py:204-227` + `ai/base.py:189-198` | **CHỐT**: giữ FAILED, phục hồi qua G8-4; chỉ thêm phân loại+metric |
| G8-2 | **P1** | `retry_async` retry MỌI exception (kể cả permanent 400/401/model sai) | `ai/base.py:191-198` | OPEN |
| G8-3 | **P1** | Caption fallback im lặng → recall tụt toàn hệ không cảnh báo cấp job | `caption/captioner.py:46-56` | OPEN |
| G8-4 | **P1** | Reconciler bỏ qua doc đã có row (kể cả FAILED) → doc FAILED do G8-1 kẹt vĩnh viễn | `store_reconciler.py:53-55` | **CHỐT**: trục phục hồi chính — retry FAILED quá tuổi + cap chống lặp |
| G8-5 | **P2** | `list_chunk_ids_by_document` scroll `limit=10000` 1 trang → orphan vector doc >10k chunk | `vectorstore/providers/qdrant/remote.py:84-94` | **CHỐT**: scroll phân trang + guard `MAX_CHUNKS_PER_DOC` |
| G8-6 | **P2** | `upsert_many` gửi toàn bộ điểm trong 1 request (G7-14 chỉ chia batch EMBED, không chia UPSERT) | `engine.py:151` + `qdrant/remote.py:75-82` | OPEN |
| G8-7 | **P2** | LocalArtifactStore ephemeral; payload trỏ `local://…` không đọc được downstream | `runtime.py:502-503` + `engine.py:124` | **CHỐT** (ghi GCS + chỉ cấp global URL) |
| G8-8 | **P2** | Mất lease giữa chừng chỉ log WARNING, KHÔNG hủy ingest → duplicate processing | `ingest_document_use_case.py:310-337` | OPEN |
| G8-9 | **P2/P3** | Không có metrics — chỉ structured log; không đo queue depth/throughput/latency | toàn service | **CHỐT**: (a)P2 counter trong /healthz; (b)P3 /metrics Prometheus khi có scraper |
| G8-10 | **P3** | `create_engine` không set `pool_size`/`max_overflow`; heartbeat+claim mở session/thread liên tục | `postgres_document_repository.py:48-49` | OPEN |
| G8-11 | **P3** | `caption_ms` cộng wall-time chồng lấn (các task song song) → metric sai | `engine.py:88-90` | OPEN |
| G8-12 | **P0** | Partial unique index `ux_ingest_jobs_active_document_id` phủ 0 row do predicate chữ HOA lệch enum lowercase → dedup active-job vô hiệu (IntegrityError-handling là dead code) | `models.py` + `migrations/0002` | **CLOSED** (5add77a / migration 0005) |

---

## G8-1 — AI outage kéo dài → job FAILED terminal, không retry (P1)

**Vấn đề:**
`retry_async` (`ai/base.py:189-198`) retry tối đa `max_retries` (mặc định 5) với backoff
`0.5·2^n + jitter` ≈ tổng ~15.5s rồi `raise`. Exception leo lên `process_next_job`
(`ingest_document_use_case.py:204-227`) → `fail_job` đặt job **FAILED terminal**. Comment
dòng 223-226 nói rõ: retry chỉ dành cho **worker chết** (stale-reaper), KHÔNG cho job lỗi.

Hệ quả: provider OpenAI rung lắc / bảo trì / rate-limit kéo dài quá ~15s → **mọi doc đang
ingest FAILED vĩnh viễn**, phải re-ingest thủ công. Đây là lỗi transient (sẽ tự khỏi) nhưng
bị xử lý như lỗi permanent.

**Fix (theo CHỐT #1 — 2026-06-07): KHÔNG dùng STALE loop.** Transient sau hết retry vẫn
`fail_job` → **FAILED terminal** (giữ hành vi hiện tại, không chiếm slot worker). Đường phục hồi
là **reconciler/cron re-ingest** doc FAILED quá tuổi (xem G8-4). Phần cần thêm ở đây chỉ là
**phân loại + đánh dấu** transient vs permanent để log/metric/alert phân biệt nguyên nhân:

```python
except Exception as exc:                       # vẫn FAILED terminal cho cả 2 loại
    err_class = classify_ingest_error(exc)     # "transient" | "permanent" (dựa G8-2)
    failed = await self._jobs.fail_job(job.id, claim_id, error_message=str(exc))
    if failed:
        await self._documents.update_status(job.document_id, DocumentStatus.FAILED, error=str(exc))
    # job log + metric ghi err_class → alert phân biệt outage (transient) vs file hỏng (permanent)
```

> Phụ thuộc G8-2 (phân loại transient). KHÔNG đổi đường lease/STALE. Phục hồi outage giao hẳn
> cho G8-4 (reconciler retry FAILED) — đây là trục chính của quyết định #1.

---

## G8-2 — `retry_async` retry mọi exception, kể cả permanent (P1)

**Vấn đề:**
`ai/base.py:191-193` — `except Exception` bắt tất cả. Lỗi permanent (HTTP 400 input quá dài,
401 sai key, model không tồn tại) cũng bị retry 5 lần ≈ 15s trước khi raise. Khi cấu hình sai,
**mỗi** call AI phí ~15s backoff → throughput sụp đổ và che lấp nguyên nhân thật.

**Fix:** whitelist transient; permanent raise ngay.

```python
_TRANSIENT = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)

async def retry_async(fn, *, max_retries, base_delay=0.5):
    attempt = 0
    while True:
        try:
            return await fn()
        except _TRANSIENT:
            attempt += 1
            if attempt > max_retries:
                raise TransientIngestError(...)   # đánh dấu cho G8-1
            await asyncio.sleep(base_delay * 2**(attempt-1) + random.uniform(0, base_delay))
        # permanent → propagate ngay, không retry
```

Import lỗi qua `openai` SDK ở adapter layer (không kéo SDK vào core nếu vi phạm §1 — bọc
exception thành domain error tại provider).

---

## G8-3 — Caption fallback im lặng → recall tụt không cảnh báo (P1)

**Vấn đề:**
`caption/captioner.py:46-56` — caption lỗi → log WARNING `caption_fallback` rồi trả
`source_text[:600]` làm caption → **vẫn đem đi embed, job vẫn COMPLETED "indexed"**. Nếu
endpoint caption hỏng diện rộng, toàn bộ doc ingest "thành công" nhưng caption = snippet thô →
search lệch toàn hệ thống, không ai biết (chỉ có WARNING rải rác, không có tín hiệu cấp job/doc).

Caption là thành phần **quyết định recall** (chính docstring captioner nói vậy) → fallback
âm thầm là nợ chất lượng nguy hiểm.

**Fix:**
- Đếm tỷ lệ `caption_fallback / tổng section` mỗi doc; vượt ngưỡng (vd >30%) → set doc trạng
  thái `degraded` (hoặc fail job để retry) thay vì COMPLETED âm thầm.
- Xuất metric `caption_fallback_total` + alert (gắn G8-9).

> Đụng pipeline quality → **eval gate bắt buộc** (golden queries) trước khi merge.

---

## G8-4 — Reconciler bỏ qua doc FAILED → kẹt vĩnh viễn (P1)

**Vấn đề:**
`store_reconciler.py:53-55` — `reconcile_store_once` chỉ enqueue khi `get_document` trả None.
Doc đã có row (kể cả **FAILED** do G8-1) sẽ bị skip → object còn trong `raw/` nhưng doc kẹt
FAILED mãi, không cơ chế nào cứu. Reconciler đóng lỗ "no-row", **không** đóng lỗ "row FAILED
transient".

**Fix (trục chính của CHỐT #1):** cho reconciler re-enqueue doc FAILED quá tuổi (`updated_at`
cũ hơn `min_age` và status FAILED), tách khỏi tombstone DELETED (DELETED vẫn skip để chống hồi
sinh).

```python
existing = await ingest_use_case.get_document(doc_id)
if existing is not None and existing.status is not DocumentStatus.FAILED:
    continue                       # COMPLETED/PROCESSING/QUEUED/DELETED → skip
# None hoặc FAILED-quá-tuổi → enqueue lại
```

**Bắt buộc kèm: backoff/cap re-ingest** để doc lỗi *permanent* (file hỏng thật, OCR luôn rỗng)
KHÔNG bị reconciler lặp vô hạn:
- Thêm cột `reconcile_attempt` (hoặc tái dùng `attempt`) + chỉ retry khi `< RECONCILE_MAX_ATTEMPTS`,
  hoặc giới hạn cửa sổ thời gian (chỉ retry doc FAILED trong N ngày gần nhất).
- Phân loại lỗi (G8-2): chỉ retry doc FAILED vì **transient**; FAILED **permanent** → để yên,
  cần can thiệp tay. (Cần lưu `err_class` từ G8-1 vào row/job log để reconciler đọc.)

> Nâng G8-4 thành trục phục hồi chính (trước đây phụ thuộc lựa chọn #1). Outage AI → doc FAILED
> hàng loạt → reconciler tự re-ingest khi provider khỏe, có cap chống lặp.

---

## G8-5 — `list_chunk_ids_by_document` scroll 1 trang `limit=10000` (P2)

**Vấn đề:**
`qdrant/remote.py:84-94` — `scroll(..., limit=10000)` lấy đúng 1 trang, không dùng
`next_page_offset`. Doc >10.000 chunk → các chunk cũ ngoài 10k **không được liệt kê** →
`engine.py:152` tính `existing - new` thiếu → stale chunk không bị prune → **orphan vector**,
search trả nội dung cũ sau re-ingest.

**Fix (CHỐT 2026-06-07): hai phần.**

**(1) Scroll phân trang đến hết** (correctness — bỏ giới hạn 1 trang):

```python
ids, offset = [], None
while True:
    points, offset = await self._client.scroll(
        collection_name=self._collection,
        scroll_filter=self._document_filter(document_id),
        with_payload=True, with_vectors=False, limit=1000, offset=offset,
    )
    ids.extend(self._existing_from_points(points))
    if offset is None:
        break
return sorted(ids)
```

> Áp cho **cả** `qdrant/remote.py` (async) lẫn `qdrant/inprocess.py` nếu cùng pattern; giữ
> parity. `_search` của mcp không đụng (đã có `top_k` riêng).

**(2) Guard `MAX_CHUNKS_PER_DOC`** (defense-in-depth — chặn doc bất thường trước khi ghi):
- Trong `engine.ingest`, sau khi build `chunk_ids` (`engine.py:128`), nếu
  `len(chunk_ids) > MAX_CHUNKS_PER_DOC` → raise lỗi **permanent** (file bất thường, không phải
  outage) → job FAILED **permanent** → reconciler KHÔNG retry (theo G8-4: chỉ retry transient),
  cần can thiệp tay.
- Default đề xuất: **`MAX_CHUNKS_PER_DOC=50000`** (~25MB text thuần ở step 75 từ) — rộng hơn
  ngưỡng scroll 10k nhiều để không chặn nhầm doc lớn hợp lệ, nhưng chặn doc 110k-chunk (50MB
  text thuần) gây nổ chi phí embed + request Qdrant.
- Param config → **validate startup** (`validate_ingest_runtime_limits()`, `runtime.py`) phải
  `> 0`; ghi vào NEW_REPO_DECISIONS (checklist #14).

```python
# engine.ingest, ngay trước embed
if len(chunk_ids) > self._max_chunks_per_doc:
    raise ChunkLimitExceededError(           # permanent: phân loại để G8-4 không retry
        f"document {doc.document_id} sinh {len(chunk_ids)} chunk > "
        f"MAX_CHUNKS_PER_DOC ({self._max_chunks_per_doc})"
    )
```

---

## G8-6 — `upsert_many` gửi toàn bộ điểm 1 request (P2)

**Vấn đề:**
G7-14 đã chia batch ở bước **EMBED** (`embedding/service.py`), nhưng `engine.py:151`
gọi `vectors.upsert_many(records)` với **toàn bộ** records, và `qdrant/remote.py:75-82`
đẩy thẳng 1 `client.upsert`. Doc nghìn chunk → 1 request Qdrant khổng lồ (vector + payload) →
nguy cơ timeout/memory, đặc biệt Qdrant Cloud.

**Fix:** chia lô upsert (vd 256 điểm/lần) trong adapter Qdrant — đối xứng với batch EMBED.

```python
for i in range(0, len(points), self._upsert_batch):
    await self._client.upsert(collection_name=self._collection, points=points[i:i+self._upsert_batch])
```

`UPSERT_BATCH_SIZE` là param config → validate startup + ghi NEW_REPO_DECISIONS.

---

## G8-7 — Artifact markdown lưu local ephemeral (P2)

**Vấn đề:**
`runtime.py:502-503` — `build_artifact_store()` luôn trả `LocalArtifactStore`.
`_prepare_markdown` ghi markdown ra đĩa local rồi đặt `artifact_uri=local://…`, field này đi
vào vector payload (`engine.py:124`) và được mcp map thành `markdown_gcs_uri` trả về
query-service. Nhưng `local://…` **không đọc được** từ service khác, và mất khi pod restart.

Hệ quả: `markdown_gcs_uri` là field "ma" — consumer tưởng lấy được markdown gốc nhưng không.
(Markdown được tái tạo mỗi attempt từ source nên không mất *dữ liệu*, nhưng *contract field*
sai.)

**CHỐT (quyết định maintainer 2026-06-07):** ngay **sau khi parse**, tải file `.md` lên **GCP
Cloud Storage luôn**, và trả về **địa chỉ URL của nó trong S3 store** (URL S3-interop
`s3://<bucket>/<key>`, đọc qua `S3_ENDPOINT_URL=https://storage.googleapis.com`). Không bao giờ
trả `local://…`; không giữ option "bỏ field".

**Cách làm:**
1. `build_artifact_store()` (`runtime.py:502-503`) trả `GcsArtifactStore` thay vì
   `LocalArtifactStore` — **tái dùng đúng S3/GCS client + bucket của parser**
   (`S3SourceParser._client_factory`, `current_source_bucket()`), không tạo client/đường đọc
   mới.
2. Trong `_prepare_markdown` (`ingest_document_use_case.py:290-308`), **sau bước parse**:
   `write_markdown(document_id, markdown)` → upload object (vd key
   `artifacts/<document_id>/markdown.md`) lên GCS và trả về **địa chỉ S3 store**
   `s3://<bucket>/artifacts/<id>/markdown.md`. `read_markdown(uri)` tải lại từ chính URL đó
   (canonical read-after-write hiện có vẫn giữ, giờ đọc từ GCS thay vì đĩa local).
3. `artifact_uri` trong payload (`engine.py:124`) và `markdown_gcs_uri` mcp trả về **luôn là
   URL S3 store** → downstream (query-service) tải markdown trực tiếp được, bền qua pod restart.

**Ràng buộc khi triển khai:**
- URL trả về dùng **đúng scheme `s3://`** mà `parse_s3_uri`/client S3-interop hiện có đọc được
  — KHÔNG phát sinh đường đọc riêng.
- Bucket/credentials/endpoint đọc từ ENV như parser (secret không vào config.yaml). Thiếu
  bucket ở production → fail-closed startup (gắn `validate_ingest_runtime_limits()`).
- Field đổi từ `local://` → `s3://` là **thay đổi giá trị contract** với query-service → báo
  consumer + version (checklist #4, #12); thêm test parity in-memory (artifact store giả trả
  URL S3 store).
- Dọn artifact GCS khi `delete_by_document` (đồng bộ vòng đời với vector) để tránh orphan
  object trong `artifacts/`.

---

## G8-8 — Mất lease không hủy ingest → duplicate processing (P2)

**Vấn đề:**
`_maintain_claim_lease` (`ingest_document_use_case.py:329-337`) khi `renew_claim` trả False
chỉ log `ingest_claim_heartbeat_lost` rồi return — **không hủy** task `engine.ingest` đang
chạy. Nếu reaper đã đổi job → STALE (claim_id=None), `complete_job`/`fail_job` sẽ fail do
claim mismatch (rowcount≠1) → job re-claim bởi worker khác → **embed + upsert lại từ đầu**.

Data-safe (chunk_id ổn định, upsert idempotent) nhưng **tốn tiền embed + double parse/OCR**.

**Fix:** truyền tín hiệu hủy (Event / `task.cancel()`) khi mất lease để dừng ingest sớm thay
vì chạy xong vô ích. `asyncio.wait_for` đã có (G7-4) sẽ dọn task ở `finally`.

---

## G8-9 — Không có metrics (P2)

**Vấn đề:** toàn service chỉ `log_event` (structured log). Không có counter/histogram để đo
**queue depth, jobs PENDING/STALE/FAILED, attempts, embed/caption latency, caption fallback
rate, doc.status sweep lag, S3 download bytes/latency**. Không có cơ sở để scale theo tải hay
phát hiện degrade (G8-3) sớm.

**Fix (tách 2 mức theo phân tích #4 — repo CHƯA có scraper):**
- **(a) P2 — ngay:** nhúng per-stage counter/gauge vào **`/healthz` sẵn có** (`compute_health`):
  queue depth, jobs PENDING/STALE/FAILED, caption fallback rate, doc.status sweep lag. Ops poll
  được ngay, không cần hạ tầng mới — đúng tinh thần [LESSONS.md:160](../handoff/LESSONS.md#L160)
  ("per-stage counter trong health/metrics").
- **(b) P3 — khi DevOps dựng scraper:** expose `/metrics` Prometheus (prometheus-client) ở
  interface layer; instrument cùng các điểm trên. Giữ §1: metric registry ở runtime/interface,
  use-case/repo không biết Prometheus (truyền callback/recorder qua contract nếu cần đo sâu).

---

## G8-10 — DB pool không cấu hình (P3)

**Vấn đề:** `postgres_document_repository.py:48-49` — `create_engine(database_url)` dùng
`pool_size=5` mặc định. Mỗi `claim`/`renew_claim`(mỗi 30s)/`update_status`/`append_job_log`
mở session riêng qua `asyncio.to_thread`. `INGEST_WORKER_COUNT>1` + heartbeat song song dễ
chạm trần pool → thread chờ connection.

**Fix:** set `pool_size`/`max_overflow`/`pool_pre_ping` theo `INGEST_WORKER_COUNT`; cân nhắc
nâng default thread executor. Param config → validate startup.

---

## G8-11 — `caption_ms` cộng wall-time chồng lấn (P3)

**Vấn đề:** `engine.py:88-90` cộng `elapsed_ms` từng task caption chạy **song song** (G7-5) →
tổng vượt thời gian thực tế, log gây hiểu sai về chi phí caption.

**Fix:** bọc một `Stopwatch` quanh `asyncio.gather` thay vì cộng per-task.

---

## G8-12 — Partial unique index phủ 0 row do lệch case predicate (P0 · CLOSED)

**Vấn đề (phát hiện khi review commit 0538910):** index dedup active-job dùng predicate chữ
HOA nhưng `IngestJobStatus` lưu chữ thường:
- `models.py` / `migrations/0002`: `status IN ('PENDING','PROCESSING','STALE')`
- `ingest_job.py`: `PENDING = "pending"` …

Postgres so chuỗi case-sensitive → `'pending' ∉ ('PENDING',…)` → index **phủ 0 row** →
`ux_ingest_jobs_active_document_id` vô hiệu. Hai `doc.ingest` redeliver đồng thời cùng `doc_id`
→ cả hai `find_active_job` trả None → cả hai INSERT thành công → **2 job active song song**;
nhánh `except IntegrityError` trong `_enqueue_sync` là **dead code**. (Vector idempotent cứu
data, nhưng mất race guard → double parse/embed.)

**Fix (đã triển khai — `5add77a`):**
- `models.py`: predicate → `('pending','processing','stale')`.
- `migrations/0005_fix_active_job_index_case.py`: drop/recreate index đúng case, dialect-aware
  (postgresql/sqlite). `downgrade` khôi phục bản cũ (chữ HOA) — có comment cảnh báo là bản lỗi.
- Test: migration-level (insert active thứ 2 → `IntegrityError`) + repo-level
  (`enqueue` trùng → trả job cũ, job-2 không tồn tại). Chạy trên SQLite (CI), **fail trước fix**.

---

## Missing tests cần bổ sung

| Test | File đề xuất | Covers |
|------|-------------|--------|
| lỗi AI transient sau hết retry → job vẫn `FAILED` terminal, nhưng job log/metric có `err_class=transient` để reconciler/alert đọc được | `tests/application/ingestion/test_ingest_document_use_case.py` | G8-1 |
| `retry_async`: permanent error raise ngay (0 retry), transient retry đủ `max_retries` | `tests/core_engine/ai/test_retry.py` | G8-2 |
| Caption fallback > ngưỡng → doc `degraded`/fail + metric tăng | `tests/core_engine/test_engine_ingest.py` | G8-3 |
| Reconciler gặp doc FAILED quá tuổi → re-enqueue; DELETED → skip | `tests/application/ingestion/test_store_reconciler.py` | G8-4 |
| `list_chunk_ids_by_document` với >10k chunk → phân trang đủ | `tests/core_engine/vectorstore/test_qdrant_remote.py` | G8-5 |
| `upsert_many` doc nghìn chunk → chia lô đúng kích thước | `tests/core_engine/vectorstore/test_qdrant_remote.py` | G8-6 |
| Mất lease giữa chừng → ingest bị cancel, không re-embed | `tests/application/ingestion/test_ingest_document_use_case.py` | G8-8 |

---

## Thứ tự fix khuyến nghị

```
G8-2  (phân loại transient/permanent)  → nền cho G8-1 + G8-4
G8-4  (reconciler retry FAILED + cap)  → TRỤC phục hồi chính (CHỐT #1)
G8-1  (giữ FAILED + phân loại/metric)  → không đổi lease, chỉ thêm err_class
G8-7  (artifact .md lên GCS, URL S3)   → CHỐT, breaking contract → báo consumer
G8-3  (caption fallback observable)    → + eval gate
G8-5  (scroll phân trang) · G8-6 (upsert chia lô) → doc lớn
G8-8  (cancel khi mất lease)
G8-9a (counter trong /healthz)         → ngay; G8-9b (/metrics) khi có scraper
G8-10 (DB pool) · G8-11 (caption_ms)   → dọn dẹp
```

---

## Trước khi fix: đọc nền bắt buộc (giống G7)

Đọc **[handoff/CONSTRAINTS.md](../handoff/CONSTRAINTS.md)** trước, đặc biệt:
- **§1 Dependency Direction**: G8-1/G8-2/G8-8 đụng use-case + core AI — không kéo `openai`/
  SQLAlchemy/Qdrant SDK vào core; bọc exception thành domain error ở provider/adapter.
- **§2 Pipeline quality gate**: G8-3/G8-6 đụng caption/embedding/vector write → **eval gate
  bắt buộc** (golden queries + source lineage), không merge bằng kiểm thử thủ công.
- **§2 Search response schema**: G8-7 đổi/bỏ key payload (`artifact_uri`/`markdown_gcs_uri`) =
  breaking contract → version + báo consumer (checklist #4, #12).
- **§3 Schema/adapter + parity**: G8-4/G8-5/G8-6/G8-10 đụng repo/adapter → mirror parity
  Postgres ↔ in-memory; G8-5/G8-6 nếu thêm param config → validate startup +
  NEW_REPO_DECISIONS (checklist #14, #15).
- **CI không có Postgres**: test G8-5/G8-6 chạy được trên backend test (mock Qdrant / SQLite),
  không fail CI.

---

## Decisions already closed

1. ~~AI down kéo dài: retry vô hạn hay FAILED + reconciler?~~ **ĐÃ CHỐT (2026-06-07):** transient
   sau hết retry → **FAILED**, rồi **reconciler/cron re-ingest** doc FAILED quá tuổi. KHÔNG giữ
   job ở PROCESSING/STALE loop chiếm slot worker. Cách vá:
   - **G8-1**: lỗi transient vẫn `fail_job` (terminal FAILED) như hiện tại — KHÔNG đổi sang STALE
     loop. Vẫn nên phân loại transient (G8-2) để **log/metric** phân biệt nguyên nhân (transient
     vs permanent) phục vụ alert.
   - **G8-4 (nâng lên trọng tâm)**: reconciler re-enqueue doc **FAILED quá tuổi** (`updated_at`
     cũ hơn `min_age`), tách tombstone DELETED. Đây là đường phục hồi chính → cần backoff/cap số
     lần re-ingest để doc lỗi permanent (file hỏng thật) không lặp vô hạn (vd cột
     `reconcile_attempt` hoặc chỉ retry trong N ngày).

2. ~~Trần chunk/doc thực tế?~~ **ĐÃ CHỐT (2026-06-07):** không neo theo "số thực tế" mà xử lý
   cứng cả hai phía — (1) **scroll phân trang đến hết** (bỏ giới hạn 10k, hết orphan vector) +
   (2) **guard `MAX_CHUNKS_PER_DOC=50000`** raise permanent → FAILED khi doc bất thường. Giữ
   G8-5 ở **P2**. Xem mục G8-5.

3. ~~Có consumer nào đọc `artifact_uri`/`markdown_gcs_uri`?~~ **ĐÃ CHỐT (2026-06-07):** sau
   parse, tải file `.md` lên GCS luôn và trả về địa chỉ URL S3 store (`s3://<bucket>/…`), không
   trả `local://`. Xem mục G8-7.

4. ~~Có stack metrics sẵn?~~ **ĐÃ CHỐT (2026-06-07):** DevOps **chưa có** scraper. → chỉ làm
   **G8-9a (P2)** — per-stage counter/gauge trong `/healthz` sẵn có (queue depth,
   PENDING/STALE/FAILED, caption fallback rate) để Ops poll ngay. **G8-9b (`/metrics`
   Prometheus) hoãn (P3)** tới khi DevOps dựng scraper. Xem mục G8-9.
